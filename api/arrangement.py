"""Bounded arrangement selection, circulation validation and optional drops."""
from __future__ import annotations

from dataclasses import dataclass

from .catalogue.contract import Catalogue
from .circulation import validate_circulation
from .domain import resolve_design
from .models import (
    ArrangementAttempt,
    ArrangementHistory,
    ArrangementRequest,
    DesignFailure,
    DesignRequest,
    DesignResultValue,
    LimitingConstraint,
    PlacementIntent,
    SearchReport,
    SolvedDesign,
)
from .zones import ZoneDerivationError, derive_zones

MAX_REPAIR_ATTEMPTS = 2
MAX_ARRANGEMENT_SOLVES = 23


def _placement_constraint(failure: DesignFailure) -> LimitingConstraint:
    return LimitingConstraint(
        code=failure.reason,
        detail=failure.detail,
        failedRequestId=failure.failedIntentId,
        exhaustive=failure.search.exhaustive,
    )


def _circulation_constraint(result) -> LimitingConstraint:
    return LimitingConstraint(
        code=result.status,
        detail=result.detail,
        disconnectedAccessIds=getattr(result, "disconnectedAccessIds", ()),
        implicatedRequestIds=getattr(result, "implicatedRequestIds", ()),
        clearanceWidthM=result.clearanceWidthM,
        attributionLimited=getattr(result, "attributionLimited", False),
        attributionLimitation=getattr(result, "attributionLimitation", None),
        gridResolutionM=result.gridResolutionM,
        exhaustive=result.exhaustive,
    )


def _history(
    request: ArrangementRequest,
    attempts: list[ArrangementAttempt],
    total_attempted: int,
) -> ArrangementHistory:
    optional_count = sum(not policy.required for policy in request.policies)
    return ArrangementHistory(
        initialSelectionId=request.selections[0].id,
        attempts=tuple(attempts),
        optionalRequestLimit=optional_count,
        maxSolveAttempts=min(MAX_ARRANGEMENT_SOLVES, len(request.selections) + optional_count),
        maxCandidatesPerSolve=request.maxCandidates,
        totalAttemptedCandidates=total_attempted,
    )


def _changed_ids(initial: tuple[PlacementIntent, ...], current: tuple[PlacementIntent, ...]) -> tuple[str, ...]:
    initial_by_id = {intent.id: intent for intent in initial}
    return tuple(sorted(
        intent.id
        for intent in current
        if intent != initial_by_id[intent.id]
    ))


@dataclass(frozen=True)
class OptionalDropPlan:
    request_id: str
    closure: frozenset[str]
    protected_ids: frozenset[str]

    @property
    def safe(self) -> bool:
        return not self.protected_ids


def plan_optional_drop(
    intents: tuple[PlacementIntent, ...],
    request_id: str,
    *,
    protected_ids: frozenset[str] = frozenset(),
) -> OptionalDropPlan:
    """Expand a request to its stable dependent/flanking closure."""
    by_id = {intent.id: intent for intent in intents}
    closure = {request_id}
    changed = True
    while changed:
        changed = False
        for intent in intents:
            if intent.referenceId in closure and intent.id not in closure:
                closure.add(intent.id)
                changed = True
        flanking_references = {
            by_id[intent_id].referenceId
            for intent_id in closure
            if intent_id in by_id and by_id[intent_id].kind == "flanking"
        }
        for intent in intents:
            if intent.kind == "flanking" and intent.referenceId in flanking_references and intent.id not in closure:
                closure.add(intent.id)
                changed = True
    frozen = frozenset(closure)
    return OptionalDropPlan(
        request_id=request_id,
        closure=frozen,
        protected_ids=frozenset(frozen & protected_ids),
    )


def resolve_arrangement(source: Catalogue, request: ArrangementRequest) -> DesignResultValue:
    """Try explicit selections, then bounded dependency-safe optional drops."""
    try:
        zone_offer = derive_zones(request.room)
    except ZoneDerivationError as error:
        constraint = LimitingConstraint(
            code=error.code,
            detail=str(error),
            exhaustive=False,
        )
        attempt = ArrangementAttempt(
            id="attempt-1",
            stage="initial",
            selectionId=request.selections[0].id,
            outcome="unsupported",
            detail=str(error),
            limitingConstraint=constraint,
            attemptedCandidates=0,
        )
        history = _history(request, [attempt], 0)
        return DesignFailure(
            status="failed",
            reason="NO_VALID_DESIGN",
            detail=f"No valid Design: {error}",
            failedIntentId="",
            search=SearchReport(
                attemptedCandidates=0,
                candidateLimit=request.maxCandidates,
                exhaustive=False,
            ),
            limitingConstraint=constraint,
            arrangementHistory=history,
        )

    policies = {policy.requestId: policy for policy in request.policies}
    anchors = frozenset(policy.requestId for policy in request.policies if policy.anchor)
    attempts: list[ArrangementAttempt] = []
    total_attempted = 0
    last_constraint: LimitingConstraint | None = None
    last_search = SearchReport(
        attemptedCandidates=0,
        candidateLimit=request.maxCandidates,
        exhaustive=True,
    )

    def evaluate(
        selection_id: str,
        intents: tuple[PlacementIntent, ...],
        stage: str,
        changed: tuple[str, ...] = (),
        dropped: tuple[str, ...] = (),
    ) -> SolvedDesign | None:
        nonlocal total_attempted, last_constraint, last_search
        design_result = resolve_design(source, DesignRequest(
            room=request.room,
            intents=intents,
            maxCandidates=request.maxCandidates,
        ))
        total_attempted += design_result.search.attemptedCandidates
        last_search = design_result.search
        attempt_id = f"attempt-{len(attempts) + 1}"
        if design_result.status == "failed":
            last_constraint = _placement_constraint(design_result)
            attempts.append(ArrangementAttempt(
                id=attempt_id,
                stage=stage,
                selectionId=selection_id,
                outcome="placement-failed",
                changedRequestIds=changed,
                droppedRequestIds=dropped,
                detail=design_result.detail,
                limitingConstraint=last_constraint,
                attemptedCandidates=design_result.search.attemptedCandidates,
            ))
            return None

        circulation = validate_circulation(
            design_result,
            request.clearanceWidthM,
            anchor_ids=anchors,
        )
        if circulation.status != "clear":
            last_constraint = _circulation_constraint(circulation)
            attempts.append(ArrangementAttempt(
                id=attempt_id,
                stage=stage,
                selectionId=selection_id,
                outcome=(
                    "circulation-blocked"
                    if circulation.status == "CIRCULATION_BLOCKED"
                    else "unsupported"
                ),
                changedRequestIds=changed,
                droppedRequestIds=dropped,
                detail=circulation.detail,
                limitingConstraint=last_constraint,
                attemptedCandidates=design_result.search.attemptedCandidates,
            ))
            return None

        attempts.append(ArrangementAttempt(
            id=attempt_id,
            stage=stage,
            selectionId=selection_id,
            outcome="solved",
            changedRequestIds=changed,
            droppedRequestIds=dropped,
            detail="Placement and whole-Design circulation both pass.",
            attemptedCandidates=design_result.search.attemptedCandidates,
        ))
        return design_result.model_copy(update={
            "zones": zone_offer.zones,
            "circulation": circulation,
            "arrangementHistory": _history(request, attempts, total_attempted),
        })

    initial_intents = request.selections[0].intents
    for selection_index, selection in enumerate(request.selections):
        solved = evaluate(
            selection.id,
            selection.intents,
            "initial" if selection_index == 0 else "repair",
            _changed_ids(initial_intents, selection.intents) if selection_index else (),
        )
        if solved is not None:
            return solved

    current = request.selections[-1].intents
    dropped_ids: set[str] = set()
    optional_order = sorted(
        (policy for policy in request.policies if not policy.required),
        key=lambda policy: (
            0 if policy.optionalKind == "decoration" else 1,
            policy.requestId,
        ),
    )
    protected = {
        policy.requestId
        for policy in request.policies
        if policy.required or policy.anchor
    }
    for policy in optional_order:
        if policy.requestId in dropped_ids:
            continue
        drop_plan = plan_optional_drop(
            current,
            policy.requestId,
            protected_ids=frozenset(protected),
        )
        closure = drop_plan.closure
        unsafe = tuple(sorted(drop_plan.protected_ids))
        if unsafe:
            attempts.append(ArrangementAttempt(
                id=f"attempt-{len(attempts) + 1}",
                stage="skipped-drop",
                selectionId=request.selections[-1].id,
                outcome="skipped",
                droppedRequestIds=tuple(sorted(closure)),
                detail=(
                    f'Drop of "{policy.requestId}" was skipped because its dependency closure '
                    f'would remove protected request(s): {", ".join(unsafe)}.'
                ),
                attemptedCandidates=0,
            ))
            continue
        dropped_ids.update(closure)
        retained = tuple(intent for intent in current if intent.id not in dropped_ids)
        if not retained:
            last_constraint = LimitingConstraint(
                code="EMPTY_DESIGN_NOT_SUPPORTED",
                detail="The bounded optional drop removed every request; FurnitureOS does not publish an empty Design.",
                exhaustive=True,
            )
            last_search = SearchReport(
                attemptedCandidates=0,
                candidateLimit=request.maxCandidates,
                exhaustive=True,
            )
            attempts.append(ArrangementAttempt(
                id=f"attempt-{len(attempts) + 1}",
                stage="drop",
                selectionId=request.selections[-1].id,
                outcome="placement-failed",
                droppedRequestIds=tuple(sorted(dropped_ids)),
                detail=last_constraint.detail,
                limitingConstraint=last_constraint,
                attemptedCandidates=0,
            ))
            continue
        solved = evaluate(
            request.selections[-1].id,
            retained,
            "drop",
            dropped=tuple(sorted(dropped_ids)),
        )
        if solved is not None:
            return solved

    assert last_constraint is not None
    history = _history(request, attempts, total_attempted)
    return DesignFailure(
        status="failed",
        reason="NO_VALID_DESIGN",
        detail=(
            f"No valid Design after {len(request.selections)} selection(s) and bounded optional drops. "
            f"Limiting constraint: {last_constraint.code}: {last_constraint.detail}"
        ),
        failedIntentId=last_constraint.failedRequestId,
        search=last_search,
        zones=zone_offer.zones,
        limitingConstraint=last_constraint,
        arrangementHistory=history,
    )
