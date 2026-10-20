"""FastAPI boundary and safe full-app static delivery."""
from __future__ import annotations

from math import isfinite
import os
from pathlib import Path, PurePosixPath
from typing import Any, Literal
from urllib.parse import unquote

from fastapi import FastAPI, HTTPException, Header
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .catalogue import Catalogue, catalogue
from .arrangement import resolve_arrangement
from .design import object_intent_fixture_room, intent_fixture_room, bedroom_design, design_fixtures, resolve_fixture
from .domain import resolve_design, validate_placement
from .live_generation import (
    GenerationProvider,
    LiveBedroomConfig,
    LiveGenerationRequest,
    BedroomGenerationRequest, LiveDesignConfig, shared_config, generate_for_room,
    LiveGenerationResult,
    generate_live_bedroom,
    public_config,
)
from .models import (
    ArrangementRequest, CatalogueGallery, DesignFixtures, DesignRequest, DesignResult, FitResult,
    FixtureSelectionRequest, Health, NudgeMutationResult, NudgeRegionResult, NudgeRequest,
    PlacementValidationRequest, PreviewDesign, ZoneDerivationFailure,
    SwapCandidateResult, SwapCurrentResult, SwapMutationResult, SwapRequest, ZoneRequest, ZoneResult,
)
from .swaps import DesignSessionStore
from .zones import ZoneDerivationError, derive_zones
from .captures import CaptureService, CaptureBodyLimit
from .capture_auth import CaptureError
from .models import SwapUnknownSession

ROOT = Path(__file__).resolve().parents[1]


def _json_safe(value: Any) -> Any:
    if isinstance(value, float) and not isfinite(value):
        if value != value:
            return "NaN"
        return "Infinity" if value > 0 else "-Infinity"
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def create_app(
    root: Path = ROOT,
    enable_catalogue_gallery: bool | None = None,
    generation_provider: GenerationProvider | None = None,
    catalogue_source: Catalogue | None = None,
    swap_store: DesignSessionStore | None = None,
    capture_repository=None,
    capture_auth=None,
    capture_vision_provider=None,
) -> FastAPI:
    """Build the API and bind static roots explicitly for tests and deployment."""
    public = root / "public"
    dist = root / "dist"
    source = catalogue if catalogue_source is None else catalogue_source
    sessions = swap_store or DesignSessionStore(source)
    captures = CaptureService(source, sessions, repository=capture_repository, auth=capture_auth,
                              vision_provider=capture_vision_provider, generation_provider=generation_provider)
    application = FastAPI(title="FurnitureOS Preview API", version="0.2.0")
    gallery_enabled = (
        os.environ.get("FURNITUREOS_ENABLE_CATALOGUE_GALLERY") == "1"
        if enable_catalogue_gallery is None
        else enable_catalogue_gallery
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["*"],
    )

    @application.exception_handler(RequestValidationError)
    async def json_safe_validation_error(_request: object, error: RequestValidationError) -> JSONResponse:
        details = jsonable_encoder(error.errors())
        return JSONResponse(status_code=422, content={"detail": _json_safe(details)})

    @application.get("/api/health", response_model=Health)
    def health() -> Health:
        return Health(status="ok")

    @application.get("/api/preview-design", response_model=PreviewDesign)
    def get_preview_design() -> PreviewDesign:
        return bedroom_design(source)

    @application.get("/api/design-fixtures", response_model=DesignFixtures)
    def get_design_fixtures() -> DesignFixtures:
        return design_fixtures()

    @application.post("/api/design-resolution", response_model=DesignResult)
    def design_resolution(request: FixtureSelectionRequest) -> DesignResult:
        resolved = resolve_fixture(request, source)
        if resolved.status == "solved":
            resolved = sessions.register(resolved, "bedroom")
        return DesignResult(root=resolved)

    @application.post("/api/design-solve", response_model=DesignResult)
    def design_solve(request: DesignRequest) -> DesignResult:
        return DesignResult(root=resolve_design(source, request))

    @application.post("/api/zones", response_model=ZoneResult)
    def zones(request: ZoneRequest) -> ZoneResult:
        try:
            return ZoneResult(root=derive_zones(request.room))
        except ZoneDerivationError as error:
            return ZoneResult(root=ZoneDerivationFailure(
                status=error.code,
                detail=str(error),
            ))

    @application.post("/api/arrangement-solve", response_model=DesignResult)
    def arrangement_solve(request: ArrangementRequest) -> DesignResult:
        return DesignResult(root=resolve_arrangement(source, request))

    @application.get("/api/live-bedroom/config", response_model=LiveBedroomConfig)
    def live_bedroom_config() -> LiveBedroomConfig:
        config = public_config()
        return config.model_copy(update={"realCallsEnabled": generation_provider is not None or config.realCallsEnabled})

    @application.post("/api/live-bedroom/generate", response_model=LiveGenerationResult)
    def live_bedroom_generate(request: BedroomGenerationRequest) -> LiveGenerationResult:
        generated = generate_live_bedroom(
            source,
            request,
            provider=generation_provider,
        )
        if generated.status == "solved":
            generated = generated.model_copy(update={
                "design": sessions.register(generated.design, "bedroom"),
            }, deep=True)
        return LiveGenerationResult(root=generated)

    @application.get("/api/live-design/config", response_model=LiveDesignConfig)
    def live_design_config(roomType: Literal["bedroom", "living-room"]) -> LiveDesignConfig:
        config = shared_config(roomType)
        return config.model_copy(update={"realCallsEnabled": generation_provider is not None or config.realCallsEnabled})

    @application.post("/api/live-design/generate", response_model=LiveGenerationResult)
    def live_design_generate(request: LiveGenerationRequest) -> LiveGenerationResult:
        generated = generate_for_room(source, request, room=(object_intent_fixture_room().model_copy(update={"id": "room-living-seating-v1"}) if request.roomType == "living-room" else intent_fixture_room()), provider=generation_provider)
        if generated.status == "solved":
            generated = generated.model_copy(update={"design": sessions.register(generated.design, request.roomType)}, deep=True)
        return LiveGenerationResult(root=generated)

    application.add_middleware(CaptureBodyLimit)
    application.include_router(captures.router())

    def session_operation(session_id, authorization, operation):
        try:
            with captures.session_access(session_id, authorization): return operation()
        except CaptureError:
            return SwapUnknownSession(status="unknown-session", detail="This Swap session is unknown to this server process. Generate or select the Design again.")

    @application.get("/api/swaps/{session_id}", response_model=SwapCurrentResult)
    def current_swap_session(session_id: str, authorization: str | None = Header(default=None)) -> SwapCurrentResult:
        return SwapCurrentResult(root=session_operation(session_id, authorization, lambda: sessions.current(session_id)))

    @application.get("/api/swaps/{session_id}/candidates", response_model=SwapCandidateResult)
    def swap_candidates(session_id: str, expectedVersion: int, instanceId: str, authorization: str | None = Header(default=None)) -> SwapCandidateResult:
        return SwapCandidateResult(root=session_operation(session_id, authorization, lambda: sessions.candidates(session_id, expectedVersion, instanceId)))

    @application.post("/api/swaps", response_model=SwapMutationResult)
    def product_swap(request: SwapRequest, authorization: str | None = Header(default=None)) -> SwapMutationResult:
        return SwapMutationResult(root=session_operation(request.sessionId, authorization, lambda: sessions.swap(request)))

    @application.get("/api/nudges/{session_id}/region", response_model=NudgeRegionResult)
    def nudge_region(session_id: str, expectedVersion: int, instanceId: str, authorization: str | None = Header(default=None)) -> NudgeRegionResult:
        return NudgeRegionResult(root=session_operation(session_id, authorization, lambda: sessions.nudge_region(session_id, expectedVersion, instanceId)))

    @application.post("/api/nudges", response_model=NudgeMutationResult)
    def product_nudge(request: NudgeRequest, authorization: str | None = Header(default=None)) -> NudgeMutationResult:
        return NudgeMutationResult(root=session_operation(request.sessionId, authorization, lambda: sessions.nudge(request)))

    if gallery_enabled:
        @application.get("/api/catalogue-gallery", response_model=CatalogueGallery)
        def get_catalogue_gallery() -> CatalogueGallery:
            return CatalogueGallery(
                catalogueVersion=source.version,
                products=source.list(),
            )

    @application.post("/api/placement-validation", response_model=FitResult)
    def placement_validation(request: PlacementValidationRequest) -> FitResult:
        try:
            return FitResult(root=validate_placement(request.product, request.room, request.placement))
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    # StaticFiles owns all filesystem path resolution. The SPA fallback below
    # never maps an untrusted URL to a filesystem path.
    application.mount("/products", StaticFiles(directory=public / "products", check_dir=False), name="products")
    application.mount("/decoders", StaticFiles(directory=public / "decoders", check_dir=False), name="decoders")
    application.mount("/assets", StaticFiles(directory=dist / "assets", check_dir=False), name="vite-assets")
    application.mount("/images", StaticFiles(directory=public / "images", check_dir=False), name="landing-images")
    application.mount(
        "/style-references",
        StaticFiles(directory=public / "style-references", check_dir=False),
        name="style-references",
    )

    @application.get("/icon.svg", include_in_schema=False)
    def icon() -> FileResponse:
        path = public / "icon.svg"
        if not path.is_file():
            raise HTTPException(404, "Not found")
        return FileResponse(path, media_type="image/svg+xml")

    def index() -> FileResponse:
        path = dist / "index.html"
        if not path.is_file():
            raise HTTPException(404, "Frontend build not found. Run npm run build or start Vite with npm run dev.")
        return FileResponse(path, media_type="text/html")

    @application.get("/", include_in_schema=False)
    def spa_root() -> FileResponse:
        return index()

    @application.get("/{path:path}", include_in_schema=False)
    def spa_history(path: str) -> FileResponse:
        decoded = path
        for _ in range(3):
            decoded_again = unquote(decoded)
            if decoded_again == decoded:
                break
            decoded = decoded_again
        parts = PurePosixPath(decoded.replace("\\", "/")).parts
        if ".." in parts or PurePosixPath(decoded).suffix or (parts and parts[0] == "api"):
            raise HTTPException(404, "Not found")
        return index()

    return application


application = create_app()
# Conventional ASGI export retained for uvicorn, tests and local tooling.
app = application
