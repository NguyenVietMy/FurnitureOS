"""Authoritative fixed-pose Product swaps and bounded process-local ownership."""
from __future__ import annotations

from dataclasses import dataclass
import secrets
from threading import RLock
import time
from typing import Callable

from .catalogue import Catalogue
from .circulation import validate_circulation
from .domain import validate_placement
from .models import (
    CirculationClear,
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

MINIMUM_CLEARANCE_M = 0.60
DEFAULT_SESSION_CAPACITY = 256
DEFAULT_SESSION_TTL_SECONDS = 30 * 60


@dataclass(frozen=True)
class FixedPoseFailure:
    code: str
    detail: str


@dataclass(frozen=True)
class _SessionRecord:
    design: SolvedDesign
    room_type: RoomType
    catalogue_version: str
    clearance_width_m: float
    expires_at: float


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
        self._validator = validator
        self._records: dict[str, _SessionRecord] = {}
        self._lock = RLock()

    def _cleanup_expired_locked(self, now: float) -> None:
        expired_ids = [
            session_id
            for session_id, record in self._records.items()
            if now >= record.expires_at
        ]
        for session_id in expired_ids:
            del self._records[session_id]

    def _lookup_locked(
        self,
        session_id: str,
    ) -> tuple[
        _SessionRecord | None,
        SwapUnknownSession | SwapExpiredSession | SwapCatalogueChanged | None,
    ]:
        record = self._records.get(session_id)
        if record is None:
            return None, SwapUnknownSession(
                status="unknown-session",
                detail="This Swap session is unknown to this server process. Generate or select the Design again.",
            )
        if self._clock() >= record.expires_at:
            del self._records[session_id]
            return None, SwapExpiredSession(
                status="expired-session",
                detail="This Swap session expired. Generate or select the Design again.",
            )
        if self._source.version != record.catalogue_version:
            del self._records[session_id]
            return None, SwapCatalogueChanged(
                status="catalogue-changed",
                detail="The Catalogue changed after this Design was created. Generate or select the Design again.",
            )
        return record, None

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

    def register(self, design: SolvedDesign, room_type: RoomType) -> SolvedDesign:
        """Admit only a complete, currently valid server-produced Design."""
        with self._lock:
            now = self._clock()
            self._cleanup_expired_locked(now)
            if len(self._records) >= self._capacity:
                return design.model_copy(update={
                    "swap": SwapUnavailable(
                        status="unavailable",
                        detail="Swap is temporarily unavailable because this server process is at session capacity.",
                    ),
                }, deep=True)
            existing_clearance = (
                design.circulation.clearanceWidthM
                if isinstance(design.circulation, CirculationClear)
                else MINIMUM_CLEARANCE_M
            )
            clearance_width_m = max(MINIMUM_CLEARANCE_M, existing_clearance)
            validated, failure = self._validator(self._source, design, clearance_width_m)
            if validated is None:
                assert failure is not None
                return design.model_copy(update={
                    "swap": SwapUnavailable(
                        status="unavailable",
                        detail=f"Swap is unavailable because the initial complete Design did not pass validation: {failure.detail}",
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
                expires_at=self._clock() + self._ttl_seconds,
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

    def _evaluate_replacement_locked(
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
                candidate, candidate_failure = self._evaluate_replacement_locked(record, instance_index, product)
                if candidate is not None:
                    compatible.append(SwapCandidate(product=product))
                else:
                    assert candidate_failure is not None
                    rejected.append(SwapRejectedCandidate(
                        product=product,
                        code=candidate_failure.code,
                        detail=candidate_failure.detail,
                    ))
            # A read cannot publish stale evidence if its immutable session expired during validation.
            if self._clock() >= record.expires_at:
                del self._records[session_id]
                return SwapExpiredSession(
                    status="expired-session",
                    detail="This Swap session expired while candidates were being checked.",
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
            candidate, candidate_failure = self._evaluate_replacement_locked(record, instance_index, replacement)
            if candidate is None:
                assert candidate_failure is not None
                return SwapRejected(
                    status="rejected",
                    code=candidate_failure.code,
                    detail=candidate_failure.detail,
                    currentVersion=session.version,
                )
            if self._clock() >= record.expires_at:
                del self._records[request.sessionId]
                return SwapExpiredSession(
                    status="expired-session",
                    detail="This Swap session expired during validation, so the replacement was not published.",
                )
            next_version = session.version + 1
            managed = self._bound_design(candidate, request.sessionId, next_version, record.clearance_width_m)
            self._records[request.sessionId] = _SessionRecord(
                design=managed,
                room_type=record.room_type,
                catalogue_version=record.catalogue_version,
                clearance_width_m=record.clearance_width_m,
                expires_at=record.expires_at,
            )
            return SwapAccepted(
                status="accepted",
                sessionId=request.sessionId,
                version=next_version,
                detail=f"{replacement.displayName} now replaces {current_product.displayName} at the unchanged pose.",
                design=managed,
            )

    def session_count(self) -> int:
        """Bounded diagnostic used by focused store tests."""
        with self._lock:
            self._cleanup_expired_locked(self._clock())
            return len(self._records)
