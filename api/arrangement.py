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
    ArrangementSelection,
    DesignFailure,
    DesignRequest,
    DesignResultValue,
    LimitingConstraint,
    PlacementIntent,
    SearchReport,
    SolvedDesign,
    ZoneOffer,
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
    selection_count: int | None = None,
) -> ArrangementHistory:
    optional_count = sum(not policy.required for policy in request.policies)
    resolved_selection_count = len(request.selections) if selection_count is None else selection_count
    return ArrangementHistory(
        initialSelectionId=request.selections[0].id,
        attempts=tuple(attempts),
        optionalRequestLimit=optional_count,
        maxSolveAttempts=min(MAX_ARRANGEMENT_SOLVES, resolved_selection_count + optional_count),
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


class ArrangementSession:
    """One chronological arrangement attempt, shared by fixtures and live generation.

    Selections are evaluated exactly once as they arrive. Optional drops are a
    separate, final operation, so a live caller can use the actual preceding
    failure before asking for the next repair.
    """

    def __init__(
        self,
        source: Catalogue,
        request: ArrangementRequest,
        *,
        selection_limit: int | None = None,
        zone_offer: ZoneOffer | None = None,
    ):
        self.source = source
        self.request = request
        self.policies = {policy.requestId: policy for policy in request.policies}
        self.anchors = frozenset(policy.requestId for policy in request.policies if policy.anchor)
        self.attempts: list[ArrangementAttempt] = []
        self.total_attempted = 0
        self.last_constraint: LimitingConstraint | None = None
        self.last_search = SearchReport(
            attemptedCandidates=0,
            candidateLimit=request.maxCandidates,
            exhaustive=True,
        )
        self.selection_limit = len(request.selections) if selection_limit is None else selection_limit
        if not 1 <= self.selection_limit <= MAX_REPAIR_ATTEMPTS + 1:
            raise ValueError("the arrangement selection limit must be between one and three")
        self.selections: list[ArrangementSelection] = []
        self.solved: SolvedDesign | None = None
        self.finished = False
        self.zone_error: ZoneDerivationError | None = None
        if zone_offer is not None:
            self.zone_offer = zone_offer
        else:
            try:
                self.zone_offer = derive_zones(request.room)
            except ZoneDerivationError as error:
                self.zone_offer = None
                self.zone_error = error

    @property
    def latest_attempt(self) -> ArrangementAttempt | None:
        return self.attempts[-1] if self.attempts else None

    def history(self) -> ArrangementHistory:
        return _history(
            self.request,
            self.attempts,
            self.total_attempted,
            selection_count=self.selection_limit,
        )

    def _evaluate(
        self,
        selection_id: str,
        intents: tuple[PlacementIntent, ...],
        stage: str,
        changed: tuple[str, ...] = (),
        dropped: tuple[str, ...] = (),
    ) -> SolvedDesign | None:
        design_result = resolve_design(self.source, DesignRequest(
            room=self.request.room,
            intents=intents,
            maxCandidates=self.request.maxCandidates,
        ), zone_offer=self.zone_offer)
        self.total_attempted += design_result.search.attemptedCandidates
        self.last_search = design_result.search
        attempt_id = f"attempt-{len(self.attempts) + 1}"
        if design_result.status == "failed":
            self.last_constraint = _placement_constraint(design_result)
            self.attempts.append(ArrangementAttempt(
                id=attempt_id,
                stage=stage,
                selectionId=selection_id,
                outcome="placement-failed",
                changedRequestIds=changed,
                droppedRequestIds=dropped,
                detail=design_result.detail,
                limitingConstraint=self.last_constraint,
                attemptedCandidates=design_result.search.attemptedCandidates,
            ))
            return None

        circulation = validate_circulation(
            design_result,
            self.request.clearanceWidthM,
            anchor_ids=self.anchors,
        )
        if circulation.status != "clear":
            self.last_constraint = _circulation_constraint(circulation)
            self.attempts.append(ArrangementAttempt(
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
                limitingConstraint=self.last_constraint,
                attemptedCandidates=design_result.search.attemptedCandidates,
            ))
            return None

        self.attempts.append(ArrangementAttempt(
            id=attempt_id,
            stage=stage,
            selectionId=selection_id,
            outcome="solved",
            changedRequestIds=changed,
            droppedRequestIds=dropped,
            detail="Placement and whole-Design circulation both pass.",
            attemptedCandidates=design_result.search.attemptedCandidates,
        ))
        solved = design_result.model_copy(update={
            "zones": self.zone_offer.zones if self.zone_offer else (),
            "circulation": circulation,
            "arrangementHistory": self.history(),
        })
        self.solved = solved
        return solved

    def submit(self, selection: ArrangementSelection) -> SolvedDesign | None:
        """Evaluate an initial or repair selection once, preserving global budgets."""
        if self.finished:
            raise RuntimeError("the arrangement session is already finished")
        if self.solved is not None:
            return self.solved
        if len(self.selections) >= self.selection_limit:
            raise ValueError("the arrangement session selection budget is exhausted")
        if not self.selections and selection != self.request.selections[0]:
            raise ValueError("the first submitted selection must match the configured initial selection")

        candidate_selections = tuple([*self.selections, selection])
        # Re-run the public request validator so incremental callers cannot evade
        # stable identity or protected-anchor rules between submissions.
        ArrangementRequest.model_validate({
            **self.request.model_dump(mode="json"),
            "selections": [item.model_dump(mode="json") for item in candidate_selections],
        })
        self.selections.append(selection)

        if self.zone_error is not None:
            self.finished = True
            constraint = LimitingConstraint(
                code=self.zone_error.code,
                detail=str(self.zone_error),
                exhaustive=False,
            )
            self.last_constraint = constraint
            self.last_search = SearchReport(
                attemptedCandidates=0,
                candidateLimit=self.request.maxCandidates,
                exhaustive=False,
            )
            self.attempts.append(ArrangementAttempt(
                id="attempt-1",
                stage="initial",
                selectionId=selection.id,
                outcome="unsupported",
                detail=str(self.zone_error),
                limitingConstraint=constraint,
                attemptedCandidates=0,
            ))
            return None

        initial_intents = self.request.selections[0].intents
        selection_index = len(self.selections) - 1
        return self._evaluate(
            selection.id,
            selection.intents,
            "initial" if selection_index == 0 else "repair",
            _changed_ids(initial_intents, selection.intents) if selection_index else (),
        )

    def finish(self) -> DesignResultValue:
        """Finish with dependency-safe optional drops; no more repairs may follow."""
        if self.solved is not None:
            self.finished = True
            return self.solved
        if self.finished:
            return self._failure()
        if not self.selections:
            raise RuntimeError("the initial selection must be submitted before finishing")
        self.finished = True

        if self.zone_error is not None:
            return self._failure(prefix=f"No valid Design: {self.zone_error}")

        current = self.selections[-1].intents
        dropped_ids: set[str] = set()
        optional_order = sorted(
            (policy for policy in self.request.policies if not policy.required),
            key=lambda policy: (
                0 if policy.optionalKind == "decoration" else 1,
                policy.requestId,
            ),
        )
        protected = {
            policy.requestId
            for policy in self.request.policies
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
                self.attempts.append(ArrangementAttempt(
                    id=f"attempt-{len(self.attempts) + 1}",
                    stage="skipped-drop",
                    selectionId=self.selections[-1].id,
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
                self.last_constraint = LimitingConstraint(
                    code="EMPTY_DESIGN_NOT_SUPPORTED",
                    detail="The bounded optional drop removed every request; FurnitureOS does not publish an empty Design.",
                    exhaustive=True,
                )
                self.last_search = SearchReport(
                    attemptedCandidates=0,
                    candidateLimit=self.request.maxCandidates,
                    exhaustive=True,
                )
                self.attempts.append(ArrangementAttempt(
                    id=f"attempt-{len(self.attempts) + 1}",
                    stage="drop",
                    selectionId=self.selections[-1].id,
                    outcome="placement-failed",
                    droppedRequestIds=tuple(sorted(dropped_ids)),
                    detail=self.last_constraint.detail,
                    limitingConstraint=self.last_constraint,
                    attemptedCandidates=0,
                ))
                continue
            solved = self._evaluate(
                self.selections[-1].id,
                retained,
                "drop",
                dropped=tuple(sorted(dropped_ids)),
            )
            if solved is not None:
                return solved

        return self._failure()

    def failure_snapshot(self, detail: str) -> DesignFailure:
        """Expose chronological feedback without authorizing optional drops."""
        if self.last_constraint is None:
            raise RuntimeError("the arrangement session has no failed solve")
        return self._failure(prefix=detail)

    def _failure(self, prefix: str | None = None) -> DesignFailure:
        assert self.last_constraint is not None
        selection_count = max(1, len(self.selections))
        detail = prefix or (
            f"No valid Design after {selection_count} selection(s) and bounded optional drops. "
            f"Limiting constraint: {self.last_constraint.code}: {self.last_constraint.detail}"
        )
        zones = self.zone_offer.zones if self.zone_offer else ()
        return DesignFailure(
            status="failed",
            reason="NO_VALID_DESIGN",
            detail=detail,
            failedIntentId=self.last_constraint.failedRequestId,
            search=self.last_search,
            zones=zones,
            limitingConstraint=self.last_constraint,
            arrangementHistory=self.history(),
        )


def resolve_arrangement(source: Catalogue, request: ArrangementRequest) -> DesignResultValue:
    """Try supplied selections once each, then bounded dependency-safe optional drops."""
    session = ArrangementSession(source, request)
    for selection in request.selections:
        solved = session.submit(selection)
        if solved is not None:
            return solved
        if session.zone_error is not None:
            break
    return session.finish()
