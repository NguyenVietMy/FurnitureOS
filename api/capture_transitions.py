"""Normalize HTTP draft transitions; SQL independently enforces the same rules.

This does not replace persisted revision, owner, lease or confirmation authority.
"""
from copy import deepcopy
from .capture_models import active_dimension_fields


def normalize_draft(before: dict, after: dict) -> dict:
    after = deepcopy(after)
    topology_changed = before.get("topology", "") != after.get("topology", "")
    fields = active_dimension_fields(after.get("topology", ""))
    dimensions_changed = any(before.get(field) != after.get(field) for field in fields)
    if after.get("topology") != "L-shaped":
        after.update(notchWidthM=None, notchDepthM=None)
    if topology_changed:
        for evidence in before.get("dimensionEvidence", []):
            field = evidence["field"]
            if not evidence.get("overrideReason", "").strip() and before.get(field) == evidence["valueM"] and after.get(field) == evidence["valueM"]:
                after[field] = None
        after["dimensionEvidence"] = []
    if topology_changed or dimensions_changed:
        after.update(dimensionsConfirmed=False, wallReviews=[])
        after["openings"] = [dict(opening, reviewed=False, **({"wallId": None} if topology_changed else {})) for opening in after.get("openings", [])]
    return after
