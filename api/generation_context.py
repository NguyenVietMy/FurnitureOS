"""Request-local continuation and work authority; never cached across requests."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
import json
from typing import Callable

from .models import ArrangementSelection
from .provider import MAX_CONVERSATION_TEXT_BYTES, ProviderCallError, ProviderUsage

_guard: ContextVar[Callable[[], None] | None] = ContextVar("generation_work_guard", default=None)


def check_work() -> None:
    guard = _guard.get()
    if guard is not None:
        guard()


@contextmanager
def work_scope(guard: Callable[[], None]):
    token = _guard.set(guard)
    try:
        yield
    finally:
        _guard.reset(token)


class Conversation:
    """Keep the initial pixels/policy prefix byte-stable and retain actual turns."""

    def __init__(self):
        self.messages: list[dict] = []
        self.calls = 0
        self.usages = []
        self.candidate = "A"
        self.duplicate = False
        self._selection_products: dict[str, str] = {}

    def user(self, value: dict) -> None:
        text = json.dumps(value, separators=(",", ":"), sort_keys=True)
        # Never merge into the initial cached message.
        if len(self.messages) > 1 and self.messages[-1]["role"] == "user":
            self.messages[-1]["content"].append({"type": "text", "text": text})
        else:
            self.messages.append({"role": "user", "content": [{"type": "text", "text": text}]})
        self.bounded()

    def bounded(self) -> None:
        size = sum(len(block.get("text", "").encode("utf-8"))
                   for message in self.messages for block in message["content"])
        if size > MAX_CONVERSATION_TEXT_BYTES or len(self.messages) > 32:
            raise ProviderCallError("schema-error", "The continued solved history exceeded its bounded context.")

    def generate(self, provider, **kwargs):
        context = json.loads(kwargs["prompt_text"])
        stable_keys = ("task", "roomType", "room", "offeredZones", "eligibleCatalogue", "rules")
        if not self.messages:
            stable = {key: context[key] for key in stable_keys}
            # Initial feasibility guidance is also stable. Corrections follow later.
            stable["placementGuidance"] = context["placementGuidance"]
            self.messages.append({"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": kwargs["image_media_type"], "data": kwargs["image_base64"]}},
                {"type": "text", "text": json.dumps(stable, separators=(",", ":"), sort_keys=True),
                 "cache_control": {"type": "ephemeral"}},
            ]})
        self.user({**{key: value for key, value in context.items() if key not in stable_keys},
                   "variant": self.candidate, "duplicateRetry": self.duplicate,
                   "variantInstruction": "Choose a distinct final Design. New candidates may choose new anchor Products; repairs retain their own identity locks."})
        check_work()
        if self.calls >= 15:
            raise ProviderCallError("schema-error", "The batch provider attempt limit was reached.")
        self.calls += 1
        try:
            reply = provider.generate(**kwargs, conversation=deepcopy(self.messages))
        except ProviderCallError as error:
            if error.attempted:
                self.usages.append(error.usage if isinstance(error.usage, ProviderUsage) else None)
            raise
        self.usages.append(reply.usage)
        check_work()
        self.messages.append({"role": "assistant", "content": [{"type": "text", "text": json.dumps(reply.payload, separators=(",", ":"), sort_keys=True)}]})
        self.bounded()
        return reply

    def accepted_selection(self, selection: ArrangementSelection) -> None:
        # Replace the whole map for this candidate; rejected raw turns never supply identities.
        self._selection_products = {intent.id: intent.productId for intent in selection.intents}

    def solved(self, design, signature: str, duplicate: bool) -> None:
        history = design.arrangementHistory
        # Skipped dependency closures are proposals, not removals from the final Design.
        retained = {placement.instanceId for placement in design.placements}
        removed = self._selection_products.keys() - retained
        # All raw assistant turns remain ordered context, including rejected proposals.
        # Only the latest server-validated selection identifies actually dropped Products.
        self.user({"serverSolvedVariant": self.candidate, "duplicate": duplicate, "signature": signature,
                   "products": [p.id for p in design.products],
                   "placements": [p.model_dump(mode="json") for p in design.placements],
                   "removed": [{"requestId": rid, "productId": self._selection_products[rid]} for rid in sorted(removed)],
                   "dropHistory": history.model_dump(mode="json") if history else None})
