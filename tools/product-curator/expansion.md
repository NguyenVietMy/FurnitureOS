# Bounded Catalogue expansion

`catalogue-expansion-v1` is separate from `bedroom20` and `living-seed-v1`.
It never starts an owner timing sample. All paths below are external except source
commands. Each batch has 1–50 ordered candidates, at most 100 MB per source and
1 GB raw sources per batch. Concurrency is one native conversion/download per batch.
Sources must be self-contained GLB with no external buffer/image paths or URLs.
Expansion native LOD subprocesses have a 120-second timeout each. The owned
preparation workspace is checked against 4 GB / 25,000 files before each candidate
and at conversion stage boundaries; this is a stage-boundary disk guard, not an
operating-system quota. Failure retains intermediates and stops further progress
once the guard is reached. Acquisition keeps two raw copies (attempt and pinned
source), bounded by twice the 1 GB batch source limit.
Keep attempts, originals, tools, journals and screenshots outside every Git checkout.
Never reset a failed directory; a new retry gets a unique attempt directory.

Discovery only reads pinned official JSONL metadata (not one JSON object):

```powershell
.venv/Scripts/python.exe tools/product-curator/discover-expansion.py --metadata-file <external>/abo-listings.json --category sofa --limit 50 --exclude-published
```

Names/types propose roles. They assign no accepted Style, Room Type or suitability.
The coordinator reviews a bounded selection before acquisition/conversion. To
construct a fully pinned intake, use the selected official GLBs only, record
actual SHA256/bytes, and fill the strict manifest below. Do not fetch an archive.
If sources are not already pinned, use `pin-expansion.mjs` as described below.

For source pinning the coordinator writes the same intake shape below, omitting
only each candidate's `sourceSha256` and `sourceBytes`, plus a real external
selection-review receipt. Then run this bounded command once in a fresh root:

```powershell
node tools/product-curator/pin-expansion.mjs --selection <reviewed-selection.json> --selection-review <actual-selection-review.md> --metadata-file <external>/abo-listings.json --state-dir <new-external-acquisition>
```

It produces `intake-pinned.json` and `sources/`, retaining every acquisition
attempt/input/failure and review-receipt digest. Failure preserves the directory;
retry under a new acquisition name. This metadata-selection review authorizes
only bounded acquisition, not visual acceptance. Preparation/review are resumable
in their separate journal after pins exist.

An intake is immutable JSON with exactly these top-level fields:

```json
{
  "schemaVersion": 1,
  "profile": "catalogue-expansion-v1",
  "batchId": "expansion-001",
  "actor": "agent",
  "reviewerIdentity": "actual-coordinator-identity",
  "purpose": "Actual Mesh suitability, functional access and private Style review",
  "metadataSha256": "660f4d01bf817802c4fc664e848af12b72246efdb15324ad1d0d2bce33f54fe9",
  "evidenceKind": "genuine-agent-curation",
  "candidates": []
}
```

Replace `candidates` with 1–50 records containing exactly: `productId` (unique
lowercase slug), `itemId` (10 uppercase alphanumerics), `modelId` (official
`3dmodel_id`, also 10 characters), `displayName`, `brand`, `colour`,
`proposedCategory`, `sourcePath`, `sourceUrl`, `sourceSha256`, `sourceBytes`.
`sourcePath` is `<last-character-of-modelId>/<modelId>.glb`; `sourceUrl` must be
`https://amazon-berkeley-objects.s3.amazonaws.com/3dmodels/original/` plus that path.
Proposal categories: bed, nightstand, wardrobe, dresser, chair, sofa, table,
coffee-table, rug, lamp. The coffee-table proposal alias still needs an actual
reviewed functional category of table; lamp means floor lamp only after Mesh review.
No accepted tags belong in intake. Duplicate Product/item/model/source hash
identities are rejected. Item/model pairs must exist in the exact pinned official
metadata file. Existing published identities may be technically prepared, but
global deduplication prevents republishing them as new Products.

For every command supply `--state-dir <external-new-batch-state> --manifest
<external-intake.json> --metadata-file <external>/abo-listings.json`. The following
examples use PowerShell's argument array to avoid copying the long paths:

```powershell
$batchArgs = @('--state-dir', '<external-state>', '--manifest', '<intake.json>', '--metadata-file', '<external>/abo-listings.json')
node tools/product-curator/expansion.mjs init @batchArgs
node tools/product-curator/expansion.mjs prepare @batchArgs --source-dir <external-pinned-glbs>
# Bounded retry of one undecided candidate after a diagnosed technical defect:
node tools/product-curator/expansion.mjs prepare @batchArgs --source-dir <external-pinned-glbs> --product-id <exact-product-id>
# Or deliberate bounded acquisition of only those exact source objects:
node tools/product-curator/expansion.mjs prepare @batchArgs --acquire
node tools/product-curator/expansion-server.mjs serve @batchArgs --port 4313
```

Open **http://127.0.0.1:4313/**. The server is read-only, loopback/same-origin,
no-store, closed-inventory only, and unavailable from production. It exposes
prepared actual Meshes, dimensions, front/side/back controls, material state and
the six hash-bound frozen Style reference images. Choose candidates in the
selector. The page makes no decisions. Stop it before CLI writes, since the state
has one exclusive writer. Hosted, CI and production contexts are refused.

Capture real screenshots during actual review. After stopping the server:

```powershell
node tools/product-curator/expansion.mjs observe @batchArgs --product-id <id> --view front --evidence-file <actual-screenshot.png>
```

Repeat for `side`, `back`, `material`, `orientation`, `dimensions`. The final
three may cite detailed screenshots of the front/orbit view and measured facts;
notes must explain what was actually inspected. Evidence is copied immutably to
owned state and bound to the acknowledged preparation/reference digest. Do not
generate placeholder images. `report` lists observation IDs and current revision.
Each candidate permits at most twelve immutable view receipts, each <=20 MB;
the same workspace disk guard checks new view evidence before it is written.

Decision document fields are exactly `schemaVersion:1`, `intakeSha256`,
`reviewerIdentity`, `evidenceKind` (must match immutable intake), and `decisions`.
Each decision needs `productId`, `decision` (`accepted`/`rejected`),
`observationIds`, and `notes` with nonempty `front`, `side`, `back`, `material`,
`orientation`, `dimensions`, `suitability`, `style`, `access`. All six inspected
view kinds must be cited. An accepted decision additionally requires `category`,
`rooms`, `privateStyleIds`, `placementClass`, `wallContactFaces`, `accessRegions`.
Accepted Style IDs are selected explicitly from `style-01` through `style-05`.
Never assign Style by title or choose a tag merely to fill coverage.

Functional rules: beds require left/right/front access; nightstand/storage,
chair/sofa and coffee table require front access. Each region explicitly gives
`face`, finite `depthM` (0.60–2.00), `required:true`, and a real functional
`purpose`. Wall contacts may be back/left/right, never a required-access face;
actual Mesh orientation decides compatibility. Rugs alone use floor-covering
and have no access/wall contacts. All others use floor-standing. Lamps may have
no required region if the actual review explains operation/limitations. Beds,
nightstands and storage support Bedroom; sofa/coffee table support Living;
chair/rug/floor lamp may explicitly support either or both. Reject broken
upholstery, incorrect roles, misleading orientation/scale, unusable materials.

```powershell
node tools/product-curator/expansion.mjs review @batchArgs --decisions-file <actual-decisions.json> --expected-revision <report-revision> --operation-id <unique-stable-id>
node tools/product-curator/expansion.mjs report @batchArgs
node tools/product-curator/promote-expansion.mjs promote @batchArgs
# Only after separately authorized local promotion and genuine review:
$deliveryArgs = @('--platform-bundle', '<external>/platform-evidence-2/BUNDLE.json', '--bundle-sha256', '<exact-bundle-sha256>', '--expected-project', 'prj_G7zuwN0gXA3nBD6QtC1hOncmMGV1', '--expected-team', 'team_pSuxCVzi76D0eTIqAWcqv9eX', '--expected-plan', 'hobby', '--delivery-method', 'git', '--proposed-runtime', 'python')
node tools/product-curator/promote-expansion.mjs promote @batchArgs @deliveryArgs --apply
```

Decisions are immutable. Retry a lost-response operation with identical document
and operation ID. For a changed review, retain the old evidence and start a new
batch/workspace. Controlled `technical-only` intake cannot become genuine by
changing flags, actor or manifest: the journal binds all frozen identities.
Conversion failure/interruption cannot count as accepted. A candidate that cannot
be prepared may instead receive a technical rejection with exactly `productId`,
`decision:"rejected"`, `technicalFailureAttemptId` and `reason`. The attempt must
be an acknowledged matching failure with an unchanged immutable failure receipt.
This omits the Product from promotion without inventing visual review notes.
Every accepted Product still requires the six actual inspected views.
Preparation `report` exposes failures, interrupted attempts, accepted/rejected
counts and owner evidence UNRUN. A successful process alone is not acceptance.

Promotion revalidates actual source/native pins, accepted output and all file
digests; dry-run inventories conflicts. New batches are canonical, immutable,
content-addressed manifests. A global lock serializes promotion; files are
staged/copied/reopened before atomic index activation last. A crash before that
index leaves orphan files unadvertised. Repeat reconciles identical hashes;
conflicting bytes stop without overwriting or deleting them. Missing/corrupt
configured index/batches fail closed in build/runtime. Absent index retains base.
The version binds the fixed legacy20/Living base and canonical ordered digest
index. Runtime, build, packaging, reports and measurement use this same union.

Promotion uses an OS byte lock on one stable, ignored .promotion.lock inode;
the installed Python interpreter holds it while the owning Node pipe is open.
OS process death releases it without deleting/recreating the inode. Process
receipts stay under the external transaction. Existing legacy PID locks are
never seized when live; proven-dead raw metadata is retained externally before
normalizing that process file. Narrow UUID-shaped pending-index paths are
ignored while active; the next serialized promotion retains abandoned raw
pending bytes externally, verifies their hashes and removes only those known
transients before continuing. Content-addressed batches/index/assets remain
visible to Git and source projection. Unknown files are never broadly ignored.

`python scripts/catalogue-coverage.py` reports unique counts, every Room/category/
Style/access cell and missing two-Product anchor alternatives separately from
the approximate-300 target. `node scripts/report-delivery.mjs` reports task
ceilings and actual local size estimates. Without the pinned receipt bundle it
says UNRUN_PLATFORM_EVIDENCE. Assertion-only caps files are rejected. See
[delivery evidence and source projection](../../docs/delivery-evidence.md) for
the named receipt schema, exact-target arguments, CLI/Git applicability and
raw/clean/deployment freeze commands. Local promotion and actual hosted
acceptance are separate gates. Git does not imply unlimited capacity.

Measurement builds use sorted pages of at most 20 Products and bind version,
page count and full-ID digest. `scripts/verify-measurement-shards.mjs <measurement-build.json>
<page0-run.json> ...` requires every identity/page once, all three actual drawn
LODs, loaded textures/materials and consistent build/version. The default
production gallery exclusion remains intact. A passing shard is not all-Product proof.
