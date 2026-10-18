"""Private Capture contracts. Unknown observations never become metric defaults."""
from __future__ import annotations
from datetime import datetime
from typing import Annotated, Literal
from pydantic import Field, RootModel
from .models import ContractModel, Finite, RoomShell
from .live_generation import LiveGenerationSuccess, LiveGenerationFailure

WallId = Literal["wall-north", "wall-east", "wall-south", "wall-west", "wall-notch-vertical", "wall-notch-horizontal"]
WALL_IDS = ("wall-north", "wall-east", "wall-south", "wall-west")
L_WALL_IDS = ("wall-north", "wall-notch-vertical", "wall-notch-horizontal", "wall-east", "wall-south", "wall-west")
DimensionField = Literal["widthM", "depthM", "heightM", "notchWidthM", "notchDepthM"]

def active_wall_ids(topology: str) -> tuple[WallId, ...]:
    return L_WALL_IDS if topology == "L-shaped" else WALL_IDS

def active_dimension_fields(topology: str) -> tuple[str, ...]:
    return ("widthM", "depthM", "heightM", "notchWidthM", "notchDepthM") if topology == "L-shaped" else ("widthM", "depthM", "heightM")
CaptureId = Annotated[str, Field(pattern=r"^[0-9a-fA-F-]{36}$")]
ShortId = Annotated[str, Field(min_length=1, max_length=64)]
MAX_INPUT_BYTES = 4_000_000
MAX_JSON_BYTES = 32_768
RETENTION_HOURS = 24

class CaptureIssue(ContractModel):
    code: str
    field: str
    detail: str

class OpeningDraft(ContractModel):
    id: ShortId
    wallId: WallId | None = None
    kind: Literal["door", "window", "unknown"] = "unknown"
    distanceFromStartM: Finite | None = None
    widthM: Finite | None = None
    bottomM: Finite | None = None
    heightM: Finite | None = None
    clearanceDepthM: Finite | None = None
    direction: Literal["unknown", "inward", "outward", "sliding", "other"] = "unknown"
    angle: Literal["unknown", "90", "other"] = "unknown"
    hingeSide: Literal["unknown", "start", "end"] = "unknown"
    reviewed: bool = False
    evidenceIds: tuple[ShortId, ...] = Field(default=(), max_length=16)

class DimensionEvidence(ContractModel):
    field: DimensionField
    valueM: Finite
    photoId: CaptureId
    photoHash: str = Field(pattern=r"^[0-9a-f]{64}$")
    overrideReason: str = Field(default="", max_length=300)

class ReferenceSegment(ContractModel):
    field: DimensionField
    start: tuple[Finite, Finite]
    end: tuple[Finite, Finite]

class ReferenceRequest(ContractModel):
    expectedRevision: int = Field(ge=1)
    photoId: CaptureId
    photoHash: str = Field(pattern=r"^[0-9a-f]{64}$")
    referenceType: Literal["a4", "measured"]
    referenceWidthM: float = Field(gt=0, le=1000, allow_inf_nan=False)
    referenceHeightM: float = Field(gt=0, le=1000, allow_inf_nan=False)
    plane: Literal["floor", "wall"]
    perspective1x: bool
    coplanar: bool
    visible: bool
    dimensionsReviewed: bool
    marksReviewed: bool
    corners: tuple[tuple[Finite, Finite], tuple[Finite, Finite], tuple[Finite, Finite], tuple[Finite, Finite]]
    segments: tuple[ReferenceSegment, ...] = Field(min_length=1, max_length=2)

class ReferenceEstimate(ContractModel):
    field: DimensionField
    valueM: float = Field(gt=0, le=1000, allow_inf_nan=False)
    sensitivity: float = Field(ge=0, allow_inf_nan=False)

class ReferenceResult(ContractModel):
    status: Literal["provisional", "typed-input-required"]
    reason: str
    estimates: tuple[ReferenceEstimate, ...] = ()
    method: Literal["coplanar-rectangle-homography-v1"] = "coplanar-rectangle-homography-v1"
    requiresConfirmation: Literal[True] = True
    photoId: CaptureId
    photoHash: str

class CalibrationRecord(ContractModel):
    request: ReferenceRequest
    result: ReferenceResult

class CaptureDraft(ContractModel):
    roomType: str = Field(default="", max_length=64)
    topology: str = Field(default="", max_length=64)
    widthM: Finite | None = None
    depthM: Finite | None = None
    heightM: Finite | None = None
    notchWidthM: Finite | None = None
    notchDepthM: Finite | None = None
    dimensionsConfirmed: bool = False
    wallReviews: tuple[WallId, ...] = Field(default=(), max_length=6)
    openings: tuple[OpeningDraft, ...] = Field(default=(), max_length=128)
    furnitureAcknowledged: bool = False
    dimensionEvidence: tuple[DimensionEvidence, ...] = Field(default=(), max_length=16)

class SemanticOpening(ContractModel):
    id: ShortId
    wallId: WallId | None
    kind: Literal["door", "window", "unknown"]
    location: Literal["near-start", "middle", "near-end", "unknown"]
    direction: Literal["unknown", "inward", "outward", "sliding", "other"]
    angle: Literal["unknown", "90", "other"]
    hingeSide: Literal["unknown", "start", "end"]
    visibility: Literal["clear", "partial", "unknown"]
    description: str = Field(max_length=300)

class CaptureSemanticProposal(ContractModel):
    openings: tuple[SemanticOpening, ...] = Field(max_length=16)
    detectedFurniture: Literal["present", "absent", "unknown"]
    observation: Literal["clear", "partial", "unknown"]

class CapturePhoto(ContractModel):
    id: CaptureId
    primaryWallId: WallId
    observedWallIds: tuple[WallId, ...] = Field(default=(), max_length=6)
    state: Literal["reserved", "accepted", "unavailable", "failed"]
    declaredBytes: int = Field(ge=1, le=MAX_INPUT_BYTES)
    inputBytes: int = Field(default=0, ge=0, le=MAX_INPUT_BYTES)
    canonicalBytes: int = Field(default=0, ge=0, le=400_000)
    sha256: str | None = None
    widthPx: int = 0
    heightPx: int = 0
    analysisStatus: Literal["pending", "complete", "failed", "unknown"] = "pending"
    analysisAttempts: int = Field(default=0, ge=0, le=2)
    semantics: CaptureSemanticProposal | None = None

class CaptureView(ContractModel):
    id: CaptureId
    revision: int = Field(ge=1)
    state: Literal["draft", "confirmed", "deleting"]
    createdAt: datetime
    expiresAt: datetime
    draft: CaptureDraft
    photos: tuple[CapturePhoto, ...] = Field(default=(), max_length=8)
    confirmedRevision: int | None = None
    roomHash: str | None = None
    room: RoomShell | None = None
    cleanupStatus: str = "none"
    calibrations: tuple[CalibrationRecord, ...] = Field(default=(), max_length=16)

class CaptureDeletionStatus(ContractModel):
    """Inaccessible lifecycle polling only; no private Capture snapshot fields."""
    id: CaptureId
    state: Literal["deleting"] = "deleting"
    inaccessible: Literal[True] = True
    cleanupStatus: str = Field(default="pending", max_length=64)

class CaptureConfig(ContractModel):
    storageReady: bool
    analysisAvailable: bool
    generationAvailable: bool
    retentionHours: Literal[24] = 24
    maxPhotos: Literal[8] = 8
    maxInputBytes: Literal[4000000] = 4_000_000
    supportedFormats: tuple[str, ...] = ("image/jpeg", "image/png")
    detail: str
    authUrl: str = ""
    publishableKey: str = ""

class CreateCapture(ContractModel):
    consent: Literal[True]

class DraftUpdate(ContractModel):
    expectedRevision: int = Field(ge=1)
    draft: CaptureDraft

class PhotoReservation(ContractModel):
    expectedRevision: int = Field(ge=1)
    declaredBytes: int = Field(ge=1, le=MAX_INPUT_BYTES)
    primaryWallId: WallId

class PhotoAssociation(ContractModel):
    expectedRevision: int = Field(ge=1)
    primaryWallId: WallId
    observedWallIds: tuple[WallId, ...] = Field(default=(), max_length=6)

class CaptureRevision(ContractModel):
    expectedRevision: int = Field(ge=1)

class CaptureGenerationRequest(CaptureRevision):
    referenceId: str = Field(pattern=r"^ref-0[1-6]$")

class CaptureReview(ContractModel):
    status: Literal["review", "confirmed"]
    capture: CaptureView
    room: RoomShell | None = None
    issues: tuple[CaptureIssue, ...] = ()

class CaptureBlocked(ContractModel):
    status: Literal["blocked"] = "blocked"
    code: str
    detail: str
    issues: tuple[CaptureIssue, ...] = ()
    providerCalls: Literal[0] = 0

class CaptureGenerated(ContractModel):
    status: Literal["generated"] = "generated"
    captureId: CaptureId
    confirmedRevision: int
    roomHash: str
    result: LiveGenerationSuccess | LiveGenerationFailure

class CaptureGenerationResult(RootModel[Annotated[CaptureBlocked | CaptureGenerated, Field(discriminator="status")]]):
    pass
