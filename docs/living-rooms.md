# Living-room generation and the seed gate

The shared `/design/live` flow requires an explicit Bedroom or Living room
declaration and a reference image. `/design/live-bedroom` and its API remain
strict Bedroom compatibility routes. FastAPI owns Catalogue eligibility,
seating Zones, Placement solving, access, circulation and mutation sessions.
Capture generation uses its persisted, confirmed Room Type; the request cannot
override it. Editing that declaration revokes the prior confirmation and Design.

A living Design requires exactly one sofa (`anchor-sofa`), one explicitly
vetted coffee table (`anchor-table`) and one chair (`anchor-chair`). All three
request and Product identities stay locked through repairs. A second chair,
one rug and one floor lamp are optional, with at most six requests. Each sofa/chair and coffee table requires
full-width 0.60 m front access. A same-yaw coffee table in front of a sofa
therefore needs at least a 0.60 m gap. The conservative 0.05 m circulation grid
may require more space than that minimum. This policy can reject familiar
tighter seating arrangements; it never shrinks access to force a fit.

Living Zone IDs use `seating-v1-<content hash>` and preserve the existing bounded,
Opening-aware rectangle derivation, including actual L floors. Their blue
outlines and text legend describe geometric offers, not group-fit promises.
Floating groups use `in_zone` plus ordinary object-relative Intents and retain
no invented wall contacts. Existing generic/Bedroom Zone identities are stable.
The live provider has at most three calls and three valid submitted selections.
The public `/api/zones` endpoint retains generic offers consumable by both
public solve endpoints. Room-Type-specific seating offers are internal to the
explicit living orchestration; clients cannot supply Zone geometry or invent IDs.
Only three valid solve failures unlock dependency-safe optional drops: rug,
lamp, then chairs, with stable request-ID ordering within a category. Both
three anchors and their dependencies remain protected, including a flanking
pair containing the required chair. Living diagnostics add no
extra diagnostic solves; Bedroom's existing bounded guidance remains intact.

## Proposal versus production

`api/catalogue/providers/abo-living-candidates.json` is a bounded eight-Product
proposal, not accepted eligibility. It contains exactly four new sofa/table
sources and references four existing chair/rug/lamp IDs. Official listing
metadata provenance is recorded in `living-source-provenance.json`. Original
GLBs, metadata downloads, native tools, preparations, journals and owner exports
remain outside Git. No other source identities are authorized by this profile.

Until a completed genuine agent or real owner review is promoted, production remains bedroom20.
An absent or invalid overlay returns `eligible-catalogue-error` with zero provider calls.
The explicit reviewed overlay is separate from the unchanged legacy seed.
Reused IDs retain every existing publication byte and their Bedroom metadata;
their reviewed Living eligibility and private tags are scoped to that Room Type.
No controlled fixture is a production fallback.

## Prepare and review locally

These commands run from the Ticket 12 checkout. Use fresh external owned paths.
The source directory must contain the exact four task-pinned GLBs; the command
has no URL/count/tool override. Preparation uses the exported converter and
independent validator, preserves full source-bound LOD0 geometry, records
source/input/tool/output hashes and never accepts a candidate.

```powershell
node tools/product-curator/prepare-living.mjs --state-dir <new-preparation-root> --source-dir <exact-task-source-directory>
node tools/product-curator/server.mjs --profile living-seed-v1 --prepared-dir <preparation-root> --state-dir <new-agent-review-root> --actor agent --reviewer-id <explicit-agent-identity> --port 0
# Optional human review uses its own separate workspace:
node tools/product-curator/server.mjs --profile living-seed-v1 --prepared-dir <preparation-root> --state-dir <new-owner-review-root> --owner-id <explicit-reviewer-identity> --actor owner --port 0
```

Use the printed numeric loopback URL. The named purpose is “Ticket12 living
seed suitability and Style review v1”, separate from the completed historical
Ticket 11 timed20 sample. A new owner root binds the profile, preparations,
reviewer identity and count durably. Start explicitly. Review actual Meshes,
compare the frozen existing Style reference images, record suitability/material/orientation/Style notes, choose private Styles and
the explicit Living room tag, and accept or reject. This profile adds only Living
eligibility; the legacy seed retains its existing Bedroom eligibility separately. Each acceptance rebuilds the source and
independently validates it. Undo precedes changing decided notes/tags. Pause
only after conversion settles; resume the same root/identity/profile. A server
restart pauses a living review and preserves its decisions. Clock uncertainty
is recorded as activity evidence and does not become a new timing gate; the
legacy timed20 clock/shutdown rules are unchanged. Do not
reuse or migrate the Ticket 11 owner root or take over its port.

Genuine agent curation has the distinct purpose "Ticket12 genuine agent living
seed suitability and Style review v1". It requires explicit Start/Resume,
actual rendered candidate inspection against frozen references, notes and
decisions, then Finish. Actor, purpose, identity and evidence mode cannot
change on reopen. Finished decisions are frozen. Agent completion is
`COMPLETED_VALID_AGENT_REVIEW`; its owner evidence remains `UNRUN`. Controlled
agent simulations and injected runners never supply genuine review evidence.
Native acceptance still rebuilds and independently validates the exact source.

Promotion requires all final decisions, a finished genuine-agent or real-owner review, validated
current acceptances spanning all five functional categories, and a supported
common private Style on a sofa/table/chair trio. An incomplete image-specific anchor
pair still returns explicit unavailability without a provider call. Private
review notes/identity and Style vocabulary stay in the local workspace, never
in public API responses or app UI.

```powershell
node tools/product-curator/promote-living.mjs --state-dir <completed-owner-root> --prepared-dir <preparation-root> --owner-id <same-identity>
# Inspect the closed dry-run inventory and conflicts before real apply:
node tools/product-curator/promote-living.mjs --state-dir <completed-owner-root> --prepared-dir <preparation-root> --owner-id <same-identity> --apply
# Genuine agent dry run, then apply only after coordinator decision/audit:
node tools/product-curator/promote-living.mjs --state-dir <completed-agent-root> --prepared-dir <preparation-root> --actor agent --reviewer-id <same-agent-identity>
node tools/product-curator/promote-living.mjs --state-dir <completed-agent-root> --prepared-dir <preparation-root> --actor agent --reviewer-id <same-agent-identity> --apply
```

The local apply path reopens the journal, accepted raw sources, output files,
native pins and neutral Catalogue projection. Controlled/automated, pending,
undone, corrupt, unsafe and incomplete evidence fails closed. It stages a
closed inventory, creates only new Product directories, preserves reused
publications exactly and atomically publishes the separate reviewed metadata
as its activation point. Metadata records truthful `reviewActor` and
`reviewEvidenceSha256`, never labels agent evidence as owner evidence. Rejected
candidates remain in the review and are omitted from publication; a complete
accepted five-category seed and common-Style anchor trio are still required.
A lock and retained transaction prevent overwriting
partial/conflicting work. On interruption, inspect the retained transaction,
lock, new directories and pending metadata before a new attempt; never reset
or automatically delete them. There is no deployment or Git publication.

Historical published manifests can lack newer diagnostic fields. Reuse keeps
the original manifest unchanged, independently validates both manifests against
the same source and requires every renderable byte to equal the rebuilt
acceptance. Its installed inventory includes the exact original manifest hash.

## Completed agent review and observable Mesh limitations

Measured width × height × depth below comes from the pinned raw Mesh, not an
independent manufacturer measurement. Upholstery is a rigid surface/texture
approximation, with no cushion deformation or seated-human simulation. Genuine
agent curation assessed silhouette, cushions, arms/back, material/texture defects,
orientation and suitability against the bound references. Inspector1 subsequently
viewed the accepted Meshes and reference rationale and found the seed suitable
within these limitations. Technical conversion success alone supplies no
suitability or Style verdict. Optional owner review remains UNRUN and is distinct
from the completed agent evidence.

| Candidate | Raw bounds (m) | Full LOD0 triangles | Review outcome and limitation |
| --- | --- | --- | --- |
| Stone & Beam Westport Linen | 2.198426 × 0.911453 × 0.901566 | 49,850 | Accepted. Intact sofa silhouette; rigid upholstery, cushion and baked-material approximations remain. |
| Stone & Beam Hillman Ivory | 1.988624 × 0.860245 × 0.991442 | 63,652 | Accepted. Intact sofa and wood base; simplified seams, shading and material transitions remain. |
| Rivet Industrial Walnut coffee table | 0.803639 × 0.576272 × 0.361342 | 3,288 | Rejected. The tall, narrow C-shaped stand is unsuitable as the primary coffee-table anchor; excluded from production. |
| Rivet Modern Pine coffee table | 0.999579 × 0.419339 × 0.548842 | 252 | Accepted as a low, broad coffee table; sparse planar topology, texture seams and edge/surface approximation remain. |

ABO licensing conflicts and unknown purchase availability remain disclosed.
Source listing titles are provenance, not current purchasing verification.

## Local proof

```powershell
.venv/Scripts/python.exe -X utf8 scripts/ticket12_proof.py --evidence-dir <fresh-external-run> --prepared-dir <preparation-root>
node tools/product-curator/prove-living.mjs --state-dir <fresh-controlled-native-root> --prepared-dir <preparation-root>
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tools/product-curator/prove-regressions.ps1 -EvidenceDir <fresh-external-regression-run>
git diff --check
```

The proof runner records native exit codes, command arguments and log hashes.
The standalone controlled server uses the existing `create_app` injection
seams, synthetic photos and the established offline Auth/Storage transport;
there is no production environment switch for it. Controlled browser proof
submits real HTTP generation and renders the actual normalized new Meshes with
`onAfterRender`, material/texture and LOD evidence. It includes rectangle/L
Capture save/review/confirm/generation and stale-session revocation. These are
integration fixtures, not paid-model quality or hosted Auth/Storage evidence.
Controlled promotion apply uses an external fixture root and metadata stamped
`CONTROLLED-NOT-OWNER-NOT-PRODUCTION`, which the production adapter rejects.

Genuine agent review completed with seven accepted and one rejected candidate,
followed by audited local promotion. The published union is 23 Products: the
unchanged original20 plus both sofas and the pine coffee table. The industrial
C-shaped stand was rejected for the coffee-table role and is absent from the
production Catalogue. The accepted set includes all five functional categories
and a supported common-Style sofa/table/chair trio. Review actor and logical
evidence hash are bound in the separate reviewed metadata; compact technical
limitations and publication hashes are recorded in `living-source-provenance.json`.
Capture-only navigation and controlled fixtures supplied no suitability decisions.
Inspector1 found the accepted seed suitable within the disclosed limitations;
its source verdict was REVISE for UI labels and this documentation. Fresh
independent inspection of the corrected source remains pending. Optional owner
evidence remains UNRUN; no actual human seed review is claimed.
Actual-photo AI and paid
provider quality remain deferred and unrun until project end. Physical-phone
and associated manual-calibration checks are waived. Tracker blockers #6/#11
remain open; bulk expansion, publication and hosting are separate gates.
