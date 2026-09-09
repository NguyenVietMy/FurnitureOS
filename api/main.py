"""FastAPI boundary and safe full-app static delivery."""
from __future__ import annotations

from math import isfinite
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import unquote

from fastapi import FastAPI, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .design import bedroom_design
from .domain import validate_placement
from .models import FitResult, Health, PlacementValidationRequest, PreviewDesign

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


def create_app(root: Path = ROOT) -> FastAPI:
    """Build the API and bind static roots explicitly for tests and deployment."""
    public = root / "public"
    dist = root / "dist"
    application = FastAPI(title="FurnitureOS Preview API", version="0.2.0")
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
        allow_methods=["GET", "POST"],
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
        return bedroom_design()

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
