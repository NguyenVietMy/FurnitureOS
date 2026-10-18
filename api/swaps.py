"""Authoritative fixed-pose Product swaps and bounded process-local ownership."""
from __future__ import annotations

from dataclasses import dataclass
import secrets
from threading import RLock
import time
from typing import Callable, Literal
from contextvars import ContextVar

from .catalogue import Catalogue
from .circulation import validate_circulation
from .domain import validate_placement
from .models import (
    CirculationClear,
    NudgeAccepted,
    NudgeCertificateMissing,
    NudgeMutationResultValue,
    NudgeRegionResultValue,
    NudgeRejected,
    NudgeRequest,
    NudgeUnavailable,
    Product,
    RoomType,
    SolvedDesign,
    SwapAccepted,
    SwapCandidate,
    SwapCatalogueChanged,
    SwapCandidateResultValue,
    SwapCandidates,
    SwapCurrent,
    SwapCurrentResultValue,
    SwapExpiredSession,
    SwapMutationResultValue,
    SwapNoCompatibleCandidates,
    SwapNoOp,
    SwapRejected,
    SwapRejectedCandidate,
    SwapRequest,
    SwapSessionAvailable,
    SwapStaleVersion,
    SwapUnavailable,
    SwapUnknownInstance,
    SwapUnknownProduct,
    SwapUnknownSession,
)
from .nudges import (
    NudgeCertificate,
    NudgeProofError,
    build_nudge_certificate,
    certificate_contains,
    nudged_placement,
)

MINIMUM_CLEARANCE_M = 0.60
DEFAULT_SESSION_CAPACITY = 256
DEFAULT_SESSION_TTL_SECONDS = 30 * 60
MAX_NUDGE_CERTIFICATE_TTL_SECONDS = 120


@dataclass(frozen=True)
class FixedPoseFailure:
    code: str
    detail: str


@dataclass(frozen=True)
class CapturedSessionBinding:
    owner_id: str
    capture_id: str
    confirmed_revision: int
    room_hash: str
    expires_at: float


CAPTURE_SESSION_ACCESS: ContextVar[CapturedSessionBinding | None] = ContextVar("capture-session-access", default=None)


@dataclass(frozen=True)
class _SessionRecord:
    design: SolvedDesign
    room_type: RoomType
    catalogue_version: str
    clearance_width_m: float
    expires_at: float
    access_policy: Literal["fixture-capability", "captured-owner"] = "fixture-capability"
    binding: CapturedSessionBinding | None = None


FixedPoseValidator = Callable[
    [Catalogue, SolvedDesign, float],
    tuple[SolvedDesign | None, FixedPoseFailure | None],
]


def validate_fixed_pose_design(
    source: Catalogue,
    design: SolvedDesign,
    clearance_width_m: float,
) -> tuple[SolvedDesign | None, FixedPoseFailure | None]:
    """Recompute every fixed Placement and whole-Design circulation."""
    canonical_products: list[Product] = []
    for product in design.products:
        canonical = source.get(product.id)
        if canonical is None:
            return None, FixedPoseFailure(
                "unknown-product",
                f'Catalogue Product "{product.id}" is no longer available.',
            )
        canonical_products.append(canonical)

    fits = []
    product_tuple = tuple(canonical_products)
    for index, (intent, product, placement) in enumerate(zip(
        design.intents,
        product_tuple,
        design.placements,
        strict=True,
    )):
        if intent.productId != product.id or placement.productId != product.id:
            return None, FixedPoseFailure(
                "misaligned-product-reference",
                f'Placement instance "{intent.id}" does not consistently reference one Catalogue Product.',
            )
        if placement.instanceId != intent.id:
            return None, FixedPoseFailure(
                "misaligned-instance-reference",
                f'Placement instance "{intent.id}" has an inconsistent stable identity.',
            )
        occupied = tuple(
            (other_product, design.placements[other_index])
            for other_index, other_product in enumerate(product_tuple)
            if other_index != index
        )
        try:
            fit = validate_placement(product, design.room, placement, occupied=occupied)
        except ValueError as error:
            return None, FixedPoseFailure("invalid-fixed-pose", str(error))
        if fit.status != "fits":
            return None, FixedPoseFailure(fit.reason, fit.detail)
        fits.append(fit)

    locally_valid = design.model_copy(update={
        "products": product_tuple,
        "fits": tuple(fits),
    }, deep=True)
    circulation = validate_circulation(locally_valid, clearance_width_m)
    if circulation.status != "clear":
        return None, FixedPoseFailure(circulation.status, circulation.detail)
    validated = locally_valid.model_copy(update={"circulation": circulation}, deep=True)
    # Re-validate the complete public contract after all aligned arrays change.
    return SolvedDesign.model_validate(validated.model_dump(mode="python")), None


def _semantic_failure(current: Product, replacement: Product, room_type: RoomType) -> FixedPoseFailure | None:
    if replacement.category != current.category:
        return FixedPoseFailure(
            "category-incompatible",
            f"{replacement.displayName} is a {replacement.category}, not a {current.category}.",
        )
    if replacement.placementClass != current.placementClass:
        return FixedPoseFailure(
            "placement-class-incompatible",
            f"{replacement.displayName} uses placement class {replacement.placementClass}, not {current.placementClass}.",
        )
    if room_type not in replacement.roomTypes:
        return FixedPoseFailure(
            "room-type-incompatible",
            f"{replacement.displayName} is not eligible for this {room_type} Room.",
        )
    return None


class DesignSessionStore:
    """A finite, process-local registry with one lock for every state decision."""

    def __init__(
        self,
        source: Catalogue,
        *,
        capacity: int = DEFAULT_SESSION_CAPACITY,
        ttl_seconds: float = DEFAULT_SESSION_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        id_factory: Callable[[], str] | None = None,
        region_id_factory: Callable[[], str] | None = None,
        validator: FixedPoseValidator = validate_fixed_pose_design,
    ) -> None:
        if capacity < 1:
            raise ValueError("Swap session capacity must be positive")
        if ttl_seconds <= 0:
            raise ValueError("Swap session TTL must be positive")
        self._source = source
        self._capacity = capacity
        self._ttl_seconds = ttl_seconds
        self._clock = clock
        self._id_factory = id_factory or (lambda: secrets.token_urlsafe(18))
        self._region_id_factory = region_id_factory or (lambda: secrets.token_urlsafe(18))
        self._validator = validator
        self._records: dict[str, _SessionRecord] = {}
        self._certificates: dict[str, NudgeCertificate] = {}
        self._certificate_tokens: dict[str, int] = {}
        self._lock = RLock()

    def _cleanup_expired_locked(self, now: float) -> None:
        expired_ids = [
            session_id
            for session_id, record in self._records.items()
            if now >= record.expires_at
        ]
        for session_id in expired_ids:
            del self._records[session_id]
            self._certificates.pop(session_id, None)
            self._certificate_tokens.pop(session_id, None)
        for session_id in tuple(self._certificates):
            if now >= self._certificates[session_id].expires_at:
                self._certificates.pop(session_id, None)

    def _lookup_locked(
        self,
        session_id: str,
    ) -> tuple[
        _SessionRecord | None,
        SwapUnknownSession | SwapExpiredSession | SwapCatalogueChanged | None,
    ]:
        record = self._records.get(session_id)
        if record is None or not ((record.access_policy == "fixture-capability" and record.binding is None) or (record.access_policy == "captured-owner" and record.binding is not None and CAPTURE_SESSION_ACCESS.get() == record.binding)):
            return None, SwapUnknownSession(
                status="unknown-session",
                detail="This Swap session is unknown to this server process. Generate or select the Design again.",
            )
        if self._clock() >= record.expires_at:
            del self._records[session_id]
            self._certificates.pop(session_id, None)
            self._certificate_tokens.pop(session_id, None)
            return None, SwapExpiredSession(
                status="expired-session",
                detail="This Swap session expired. Generate or select the Design again.",
            )
        if self._source.version != record.catalogue_version:
            del self._records[session_id]
            self._certificates.pop(session_id, None)
            self._certificate_tokens.pop(session_id, None)
            return None, SwapCatalogueChanged(
                status="catalogue-changed",
                detail="The Catalogue changed after this Design was created. Generate or select the Design again.",
            )
        return record, None

    @staticmethod
    def _version(record: _SessionRecord) -> int:
        session = record.design.swap
        assert isinstance(session, SwapSessionAvailable)
        return session.version

    def _invalidate_certificate_locked(self, session_id: str) -> None:
        self._certificates.pop(session_id, None)
        self._certificate_tokens[session_id] = self._certificate_tokens.get(session_id, 0) + 1

    def _bound_design(
        self,
        design: SolvedDesign,
        session_id: str,
        version: int,
        clearance_width_m: float,
    ) -> SolvedDesign:
        return design.model_copy(update={
            "swap": SwapSessionAvailable(
                status="available",
                sessionId=session_id,
                version=version,
                catalogueVersion=self._source.version,
                clearanceWidthM=clearance_width_m,
            ),
        }, deep=True)

    def register(self, design: SolvedDesign, room_type: RoomType, *, binding: CapturedSessionBinding | None = None) -> SolvedDesign:
        """Admit only a complete, currently valid server-produced Design."""
        existing_clearance = (
            design.circulation.clearanceWidthM
            if isinstance(design.circulation, CirculationClear)
            else MINIMUM_CLEARANCE_M
        )
        clearance_width_m = max(MINIMUM_CLEARANCE_M, existing_clearance)
        catalogue_version = self._source.version
        validated, failure = self._validator(self._source, design, clearance_width_m)
        if validated is None:
            assert failure is not None
            return design.model_copy(update={
                "swap": SwapUnavailable(
                    status="unavailable",
                    detail=f"Swap and Nudge are unavailable because the initial complete Design did not pass validation: {failure.detail}",
                ),
            }, deep=True)
        with self._lock:
            if self._source.version != catalogue_version:
                return design.model_copy(update={
                    "swap": SwapUnavailable(
                        status="unavailable",
                        detail="The Catalogue changed during validation. Generate or select the Design again.",
                    ),
                }, deep=True)
            now = self._clock()
            self._cleanup_expired_locked(now)
            if len(self._records) >= self._capacity:
                return design.model_copy(update={
                    "swap": SwapUnavailable(
                        status="unavailable",
                        detail="Swap and Nudge are temporarily unavailable because this server process is at session capacity.",
                    ),
                }, deep=True)
            session_id = self._id_factory()
            while session_id in self._records:
                session_id = self._id_factory()
            managed = self._bound_design(validated, session_id, 1, clearance_width_m)
            self._records[session_id] = _SessionRecord(
                design=managed,
                room_type=room_type,
                catalogue_version=self._source.version,
                clearance_width_m=clearance_width_m,
                expires_at=self._clock() + (min(self._ttl_seconds, max(0, binding.expires_at-time.time())) if binding else self._ttl_seconds),
                access_policy="captured-owner" if binding else "fixture-capability",
                binding=binding,
            )
            return managed

    def current(self, session_id: str) -> SwapCurrentResultValue:
        with self._lock:
            record, failure = self._lookup_locked(session_id)
            if failure is not None:
                return failure
            assert record is not None
            version = record.design.swap.version if isinstance(record.design.swap, SwapSessionAvailable) else 1
            return SwapCurrent(
                status="current",
                sessionId=session_id,
                version=version,
                design=record.design,
            )

    @staticmethod
    def _instance_index(design: SolvedDesign, instance_id: str) -> int | None:
        return next((
            index for index, placement in enumerate(design.placements)
            if placement.instanceId == instance_id
        ), None)

    def _evaluate_replacement(
        self,
        record: _SessionRecord,
        instance_index: int,
        replacement: Product,
    ) -> tuple[SolvedDesign | None, FixedPoseFailure | None]:
        current = record.design.products[instance_index]
        semantic_failure = _semantic_failure(current, replacement, record.room_type)
        if semantic_failure is not None:
            return None, semantic_failure
        intents = list(record.design.intents)
        placements = list(record.design.placements)
        products = list(record.design.products)
        intents[instance_index] = intents[instance_index].model_copy(update={"productId": replacement.id})
        placements[instance_index] = placements[instance_index].model_copy(update={"productId": replacement.id})
        products[instance_index] = replacement
        provisional = record.design.model_copy(update={
            "intents": tuple(intents),
            "placements": tuple(placements),
            "products": tuple(products),
        }, deep=True)
        return self._validator(self._source, provisional, record.clearance_width_m)

    def candidates(
        self,
        session_id: str,
        expected_version: int,
        instance_id: str,
    ) -> SwapCandidateResultValue:
        with self._lock:
            record, failure = self._lookup_locked(session_id)
            if failure is not None:
                return failure
            assert record is not None
            session = record.design.swap
            assert isinstance(session, SwapSessionAvailable)
            if expected_version != session.version:
                return SwapStaleVersion(
                    status="stale-version",
                    currentVersion=session.version,
                    detail=f"The Design is now version {session.version}; refresh before choosing another Product.",
                )
            instance_index = self._instance_index(record.design, instance_id)
            if instance_index is None:
                return SwapUnknownInstance(
                    status="unknown-instance",
                    currentVersion=session.version,
                    detail=f'No Placement instance has id "{instance_id}".',
                )
            current_product = record.design.products[instance_index]
        compatible: list[SwapCandidate] = []
        rejected: list[SwapRejectedCandidate] = []
        for product in sorted(self._source.list(), key=lambda value: (value.displayName, value.id)):
            if product.id == current_product.id:
                continue
            if (
                product.category != current_product.category
                or product.placementClass != current_product.placementClass
                or record.room_type not in product.roomTypes
            ):
                continue
            candidate, candidate_failure = self._evaluate_replacement(record, instance_index, product)
            if candidate is not None:
                compatible.append(SwapCandidate(product=product))
            else:
                assert candidate_failure is not None
                rejected.append(SwapRejectedCandidate(
                    product=product,
                    code=candidate_failure.code,
                    detail=candidate_failure.detail,
                ))
        with self._lock:
            current, current_failure = self._lookup_locked(session_id)
            if current_failure is not None:
                return current_failure
            assert current is not None
            current_version = self._version(current)
            if current_version != expected_version or current is not record:
                return SwapStaleVersion(
                    status="stale-version",
                    currentVersion=current_version,
                    detail=f"The Design is now version {current_version}; refresh before choosing another Product.",
                )
            if not compatible:
                return SwapNoCompatibleCandidates(
                    status="no-compatible-candidates",
                    currentVersion=session.version,
                    instanceId=instance_id,
                    rejected=tuple(rejected),
                    detail="No other Catalogue Product preserves this complete Design at the selected pose.",
                )
            return SwapCandidates(
                status="candidates",
                sessionId=session_id,
                currentVersion=session.version,
                instanceId=instance_id,
                candidates=tuple(compatible),
                rejected=tuple(rejected),
                detail=f"{len(compatible)} compatible Product choice{'s' if len(compatible) != 1 else ''} validated.",
            )

    def swap(self, request: SwapRequest) -> SwapMutationResultValue:
        with self._lock:
            record, failure = self._lookup_locked(request.sessionId)
            if failure is not None:
                return failure
            assert record is not None
            session = record.design.swap
            assert isinstance(session, SwapSessionAvailable)
            if request.expectedVersion != session.version:
                return SwapStaleVersion(
                    status="stale-version",
                    currentVersion=session.version,
                    detail=f"The Design is now version {session.version}; refresh before trying this Swap again.",
                )
            instance_index = self._instance_index(record.design, request.instanceId)
            if instance_index is None:
                return SwapUnknownInstance(
                    status="unknown-instance",
                    currentVersion=session.version,
                    detail=f'No Placement instance has id "{request.instanceId}".',
                )
            current_product = record.design.products[instance_index]
            if current_product.id == request.replacementProductId:
                return SwapNoOp(
                    status="no-op",
                    currentVersion=session.version,
                    detail=f"{current_product.displayName} is already used by this Placement; the Design was not changed.",
                )
            replacement = self._source.get(request.replacementProductId)
            if replacement is None:
                return SwapUnknownProduct(
                    status="unknown-product",
                    currentVersion=session.version,
                    detail=f'Catalogue Product "{request.replacementProductId}" does not exist.',
                )
        candidate, candidate_failure = self._evaluate_replacement(record, instance_index, replacement)
        if candidate is None:
            assert candidate_failure is not None
            return SwapRejected(
                status="rejected",
                code=candidate_failure.code,
                detail=candidate_failure.detail,
                currentVersion=session.version,
            )
        with self._lock:
            current, current_failure = self._lookup_locked(request.sessionId)
            if current_failure is not None:
                return current_failure
            assert current is not None
            current_version = self._version(current)
            if current_version != request.expectedVersion or current is not record:
                return SwapStaleVersion(
                    status="stale-version",
                    currentVersion=current_version,
                    detail=f"The Design is now version {current_version}; refresh before trying this Swap again.",
                )
            next_version = session.version + 1
            managed = self._bound_design(candidate, request.sessionId, next_version, record.clearance_width_m)
            self._records[request.sessionId] = _SessionRecord(
                design=managed,
                room_type=record.room_type,
                catalogue_version=record.catalogue_version,
                clearance_width_m=record.clearance_width_m,
                expires_at=record.expires_at,
                access_policy=record.access_policy,
                binding=record.binding,
            )
            self._invalidate_certificate_locked(request.sessionId)
            return SwapAccepted(
                status="accepted",
                sessionId=request.sessionId,
                version=next_version,
                detail=f"{replacement.displayName} now replaces {current_product.displayName} at the unchanged pose.",
                design=managed,
            )

    def nudge_region(
        self,
        session_id: str,
        expected_version: int,
        instance_id: str,
    ) -> NudgeRegionResultValue:
        with self._lock:
            record, failure = self._lookup_locked(session_id)
            if failure is not None:
                return failure
            assert record is not None
            current_version = self._version(record)
            if expected_version != current_version:
                return SwapStaleVersion(
                    status="stale-version",
                    currentVersion=current_version,
                    detail=f"The Design is now version {current_version}; request a new Nudge region.",
                )
            if self._instance_index(record.design, instance_id) is None:
                return SwapUnknownInstance(
                    status="unknown-instance",
                    currentVersion=current_version,
                    detail=f'No Placement instance has id "{instance_id}".',
                )
            issuance_token = self._certificate_tokens.get(session_id, 0) + 1
            self._certificate_tokens[session_id] = issuance_token
            expires_at = min(record.expires_at, self._clock() + MAX_NUDGE_CERTIFICATE_TTL_SECONDS)
            region_id = self._region_id_factory()

        try:
            certificate, response = build_nudge_certificate(
                record.design,
                instance_id,
                record.clearance_width_m,
                region_id=region_id,
                session_id=session_id,
                version=current_version,
                expires_at=expires_at,
                clock=self._clock,
            )
        except (NudgeProofError, ValueError) as error:
            return NudgeUnavailable(
                status="unavailable",
                currentVersion=current_version,
                instanceId=instance_id,
                detail=str(error),
            )

        with self._lock:
            current, current_failure = self._lookup_locked(session_id)
            if current_failure is not None:
                return current_failure
            assert current is not None
            live_version = self._version(current)
            if live_version != expected_version or current is not record:
                return SwapStaleVersion(
                    status="stale-version",
                    currentVersion=live_version,
                    detail=f"The Design is now version {live_version}; request a new Nudge region.",
                )
            if self._certificate_tokens.get(session_id) != issuance_token:
                return NudgeUnavailable(
                    status="unavailable",
                    currentVersion=live_version,
                    instanceId=instance_id,
                    detail="A newer Nudge region request superseded this one.",
                )
            if self._clock() >= certificate.expires_at:
                return NudgeUnavailable(
                    status="unavailable",
                    currentVersion=live_version,
                    instanceId=instance_id,
                    detail="The Nudge region expired while it was being certified.",
                )
            self._certificates[session_id] = certificate
            return response

    def nudge(self, request: NudgeRequest) -> NudgeMutationResultValue:
        with self._lock:
            record, failure = self._lookup_locked(request.sessionId)
            if failure is not None:
                return failure
            assert record is not None
            current_version = self._version(record)
            if request.expectedVersion != current_version:
                return SwapStaleVersion(
                    status="stale-version",
                    currentVersion=current_version,
                    detail=f"The Design is now version {current_version}; request a new Nudge region.",
                )
            instance_index = self._instance_index(record.design, request.instanceId)
            if instance_index is None:
                return SwapUnknownInstance(
                    status="unknown-instance",
                    currentVersion=current_version,
                    detail=f'No Placement instance has id "{request.instanceId}".',
                )
            certificate = self._certificates.get(request.sessionId)
            if (
                certificate is None
                or certificate.region_id != request.regionId
                or certificate.version != request.expectedVersion
                or certificate.instance_id != request.instanceId
                or self._clock() >= certificate.expires_at
            ):
                if certificate is not None and self._clock() >= certificate.expires_at:
                    self._certificates.pop(request.sessionId, None)
                return NudgeCertificateMissing(
                    status="certificate-missing",
                    currentVersion=current_version,
                    detail="This Nudge region is missing, replaced, or expired. Request a new safe region.",
                )
            if not certificate_contains(certificate, request.target):
                return NudgeRejected(
                    status="rejected",
                    code="outside-certified-region",
                    currentVersion=current_version,
                    detail="The requested Placement is outside the server-certified Nudge region.",
                )
            if request.target == certificate.origin:
                return NudgeRejected(
                    status="rejected",
                    code="no-op",
                    currentVersion=current_version,
                    detail="The Placement is already at that position.",
                )
            placements = list(record.design.placements)
            placements[instance_index] = nudged_placement(
                record.design.products[instance_index],
                record.design.room,
                placements[instance_index],
                request.target,
            )
            provisional = record.design.model_copy(update={"placements": tuple(placements)}, deep=True)

        candidate, candidate_failure = self._validator(self._source, provisional, record.clearance_width_m)
        if candidate is None:
            assert candidate_failure is not None
            return NudgeRejected(
                status="rejected",
                code=candidate_failure.code,
                detail=candidate_failure.detail,
                currentVersion=current_version,
            )

        with self._lock:
            current, current_failure = self._lookup_locked(request.sessionId)
            if current_failure is not None:
                return current_failure
            assert current is not None
            live_version = self._version(current)
            live_certificate = self._certificates.get(request.sessionId)
            if live_version != request.expectedVersion or current is not record:
                return SwapStaleVersion(
                    status="stale-version",
                    currentVersion=live_version,
                    detail=f"The Design is now version {live_version}; the Nudge was not published.",
                )
            if (
                live_certificate is not certificate
                or self._clock() >= certificate.expires_at
            ):
                return NudgeCertificateMissing(
                    status="certificate-missing",
                    currentVersion=live_version,
                    detail="The Nudge certificate changed or expired during validation, so nothing was published.",
                )
            next_version = live_version + 1
            managed = self._bound_design(candidate, request.sessionId, next_version, record.clearance_width_m)
            self._records[request.sessionId] = _SessionRecord(
                design=managed,
                room_type=record.room_type,
                catalogue_version=record.catalogue_version,
                clearance_width_m=record.clearance_width_m,
                expires_at=record.expires_at,
                access_policy=record.access_policy,
                binding=record.binding,
            )
            self._invalidate_certificate_locked(request.sessionId)
            return NudgeAccepted(
                status="accepted",
                sessionId=request.sessionId,
                version=next_version,
                detail="The Product was moved within its certified safe region.",
                design=managed,
            )

    def session_count(self) -> int:
        """Bounded diagnostic used by focused store tests."""
        with self._lock:
            self._cleanup_expired_locked(self._clock())
            return len(self._records)

    def certificate_count(self) -> int:
        """Bounded diagnostic used by focused store tests."""
        with self._lock:
            self._cleanup_expired_locked(self._clock())
            return len(self._certificates)

    def captured_binding(self, session_id: str) -> CapturedSessionBinding | None:
        """Internal admission metadata only; callers must verify principal before geometry."""
        with self._lock:
            record = self._records.get(session_id)
            return record.binding if record and record.access_policy == "captured-owner" else None

    def revoke_capture(self, capture_id: str) -> None:
        with self._lock:
            for session_id, record in tuple(self._records.items()):
                if record.binding and record.binding.capture_id == capture_id:
                    self._records.pop(session_id, None)
                    self._certificates.pop(session_id, None)
                    self._certificate_tokens.pop(session_id, None)
