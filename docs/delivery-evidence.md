# Delivery evidence and exact source projection

These tools prepare reviewable local evidence. They grant no commit, push, Git
connection, cloud deployment, alias, migration or public-readiness authority.
Catalogue acceptance still requires actual Mesh review and native validation.

## Current local catalogue

The approved Queue1 local promotion contains 315 unique Products: the preserved
original 23 plus 292 genuine native-review acceptances from nine exact batches.
Of 300 selected inputs, two were visually rejected and six technically rejected;
none of those eight is published. There are 5,058 Product files totaling
542,883,278 bytes. All twenty required five-Style bed/sofa/table/chair anchor
cells have at least two distinct eligible Products. Source-screened proposals,
failed attempts and superseded intake batches do not count toward this union.

This inventory describes local source. The recorded target still has no Git
connection, and actual hosted build/runtime, deployment and public acceptance
remain UNRUN. The final builder handoff supplies the complete current-source
test, rendering, delivery and raw/Git-clean projection receipts. Independent
implementation inspection is a separate gate.

## Target receipt bundle

Run from the isolated source root. The approved proposed target is project
`prj_G7zuwN0gXA3nBD6QtC1hOncmMGV1`, team
`team_pSuxCVzi76D0eTIqAWcqv9eX`, plan `hobby`, delivery method `git`.
Supply these independently of whatever a bundle claims:

```powershell
$run = 'C:/Users/VietM/AppData/Local/Temp/claudex-loop/demo-readiness-20261029-132819'
$deliveryArgs = @('--platform-bundle', "$run/platform-evidence-1/BUNDLE.json", '--bundle-sha256', 'b421510f0996c0ee7a70be856a95725b7b3d2fb576aab679fd4af9ac2c7495a8', '--expected-project', 'prj_G7zuwN0gXA3nBD6QtC1hOncmMGV1', '--expected-team', 'team_pSuxCVzi76D0eTIqAWcqv9eX', '--expected-plan', 'hobby', '--delivery-method', 'git')
node scripts/report-delivery.mjs @deliveryArgs
```

`scripts/lib/platform-evidence.mjs` validates the strict existing coordinator
bundle: schemaVersion 1, createdAt, status COORDINATOR_READ_EVIDENCE_ONLY,
expectedTarget with proposedDeliveryMethod, hostedAcceptance UNRUN, note, and
eight named files with exact path/bytes/SHA256. They are team-receipt.json,
team-redacted.json, project-receipt.json, project-redacted.json,
limits-receipt.json, limits.html, git-receipt.json, git.html. Unknown fields,
links, changed bytes, malformed times, wrong target or method fail closed.
Authenticated read commands, API routes, scope, status, observed fields and
canonical normalized redacted-response hashes are checked. Document receipts
bind URL, effective URL, HTTP status, content type, fetch times and snapshot bytes.
Recorded commands are data; the verifier never executes them.

The report separates these evidence levels:

- Verified retained: the named bytes, redacted target/team metadata, normalized
  digests and recognized statements in the primary document snapshots.
- Asserted: authenticated raw response digests whose raw responses were not
  retained, and the plan's historical 23 GB disk claim. This is coordinator read
  evidence, with no independent hosted-audit claim.
- Unknown/unrun: actual build allocation, function bundle platform cap, current
  hosted compatibility and exact runtime acceptance. The recorded gitLink is
  null. No Git connection is inferred or created.

The retained limits snapshot establishes 100,000,000 source bytes and 15,000
source files for CLI uploads only. These checks fail when exceeded under CLI;
under Git they are NOT_APPLICABLE, while actual source bytes/counts remain in
the report. It establishes a 2,700-second build limit. Its disk table starts at
32 GB, differing from the plan's 23 GB prose; actual allocation remains unknown.
No function byte limit is invented from the task ceiling or an external link.
The document's output-file statement is reported only when present in the
retained snapshot. Actual time/storage acceptance remains unrun.

An optional bounded ten-file revision adds exactly functions-receipt.json and
functions.html. It validates their named hashes, fetch metadata and actual
primary text. Current platform-evidence-2/BUNDLE.json SHA256 is
`3eda7b4f8c58c86fc4b1b77b91e26938840f6bf5490ddc39b2bbd4a0263b6bfd`;
its original eight files are byte-identical to platform-evidence-1. For this
revision use the same explicit target flags plus `--proposed-runtime python`:

```powershell
node scripts/report-delivery.mjs --platform-bundle "$run/platform-evidence-2/BUNDLE.json" --bundle-sha256 3eda7b4f8c58c86fc4b1b77b91e26938840f6bf5490ddc39b2bbd4a0263b6bfd --expected-project prj_G7zuwN0gXA3nBD6QtC1hOncmMGV1 --expected-team team_pSuxCVzi76D0eTIqAWcqv9eX --expected-plan hobby --delivery-method git --proposed-runtime python
```

The standard Python uncompressed 500 MB cap comes from retained document text.
Applicability is Python only; source api/index.py proposes that runtime, while
actual hosting/runtime remains UNRUN. Framework metadata never selects a
runtime. Without the explicit proposed runtime the numeric fact is retained but
its check says UNRUN_RUNTIME_APPLICABILITY. The historical eight-file bundle
remains UNKNOWN for function size even when Python is proposed. Nine files,
arbitrary extra sources, changed snapshots or unsupported runtime declarations
fail closed. The 5 GB large-function option is NOT_RELIED_ON: eligibility,
Fluid/ActiveCPU and configuration remain unverified and no setting is changed.
The 250 MB task ceiling stays stricter under both delivery methods. Hosted
acceptance/public activation still require actual evidence and authorization.

Defensive task ceilings apply under either method: 1,500,000,000 Product bytes,
25,000 Product files, 1,600,000,000 dist bytes, 20,000,000 manifest bytes and
250,000,000 function bytes. Estimates describe local installed files; dependency
symlinks are excluded from the Node disk estimate. Actual hosted outputs are a
separate required receipt. Do not silently drop Products or alter quality to fit.

## Two-view pre-inspection freeze

Use a new external destination every time, after all intended source/data
changes and local proofs are complete. Failed directories are retained.

```powershell
.venv/Scripts/python.exe scripts/source_projection.py freeze --out "$run/builder/projection-FRESH-NAME"
Get-FileHash "$run/builder/projection-FRESH-NAME/PROJECTION.json" -Algorithm SHA256
.venv/Scripts/python.exe scripts/source_projection.py verify-raw --projection "$run/builder/projection-FRESH-NAME/PROJECTION.json" --projection-sha256 <printed-sha256>
node scripts/report-delivery.mjs @deliveryArgs --source-projection "$run/builder/projection-FRESH-NAME/PROJECTION.json" --source-projection-sha256 <printed-sha256>
```

The projection inventories every tracked/nonignored path plus the baseline tree,
including intended deletions. `raw/` holds exact working bytes. `deployment/`
holds the expected Linux checkout bytes after Git clean and applicable EOL rules.
PROJECTION.json pins every path, mode, raw bytes/SHA256, clean bytes/SHA256,
expected Git blob OID and deployment bytes/SHA256, effective attributes, EOL
configuration, baseline commit and real-index before/after hashes. It reports
normalization differences. `objects.git/` is a fresh isolated external object
store only: no commit, tree, external staging or real-index write is made.
Git global/system configuration is disabled for this projection; effective
attributes must match the real source context. Custom filters, encodings, ident,
symlinks, submodules, unsafe paths and unsupported attribute contexts are refused.
The service bound is 2 GB / 30,000 source paths, with disk headroom checked.
Blob reading streams one object at a time.

New expansion JSON uses explicit `-text` attributes. Its raw and deployment
SHA256 must match, content-addressed batch filenames/index references must agree,
and canonical parsed-content digests must match through actual Git Windows and
Linux checkout filters. This is an offline serialization/filter check, not an
actual cross-OS application build. Existing legacy asset attributes/bytes stay
unchanged. Before any expansion is configured the full projection reports
UNCONFIGURED_NO_EXPANSION_METADATA; controlled parity tests cover the new format.

Give the fresh inspector both trees and the exact pinned PROJECTION.json along
with required proof receipts. This milestone's projection prepares that handoff;
it is not inspection approval. Later source, attributes or proof changes require
a new complete freeze and fresh inspection. Final catalogue promotion invalidates
an earlier source freeze and requires final all-Product proofs and a new freeze.

## After independently authorized publication

An authorized operator creates the actual commit later. This builder tool only
reads that commit and reconstructs its paths; it never creates a commit:

```powershell
.venv/Scripts/python.exe scripts/source_projection.py verify-commit --projection <inspected-PROJECTION.json> --projection-sha256 <inspected-sha256> --commit <actual-full-commit-sha>
```

The command requires unchanged current source/config/attributes, exact committed
path set, modes, clean blob OIDs/bytes, all intended deletions, and reconstructed
deployment SHA256/byte equality. It writes fresh external `committed-*/clean`
and `committed-*/deployment` trees, records the actual commit/tree SHA and reruns
expansion EOL parity bound to those exact blobs. Any mismatch blocks the handoff;
do not reuse approval for corrected source. Hosted acceptance stays UNRUN.

## Later actual hosted receipt

`platformReady` stays false without `verifyHostedReceipt` accepting an actual
retained matching build/deployment receipt. A READY string, URL, branch name,
empty source metadata or boolean cannot satisfy this contract. Never manufacture
receipts to satisfy the schema; fields the platform evidence cannot establish
remain unrun and need an explicit reviewed evidence-contract extension.

The future receipt is strict schemaVersion 1, kind
ACTUAL_VERCEL_BUILD_DEPLOYMENT, observedAt, exact target, source (commitSha,
treeSha, projectionSha256), deploymentId, buildId, build (status SUCCEEDED,
outputSha256/outputBytes/staticFiles/functionBytes/durationSeconds/diskBytes),
runtimeConfiguration (sha256/status VERIFIED_ACTUAL_DEPLOYMENT), and retainedRead
(named JSON path, bytes, SHA256). The retained authenticated GET receipt requires
kind, startedAt/finishedAt, tool version, method, exact deployment/team route,
exitCode, rawResponseSha256, retainedRedactedCanonicalSha256, redaction limit and
normalized observed target/source/build/runtime fields. Raw responses are not
claimed retained; normalized observed fields are hash checked. Metrics must be
actual, with matching retained build/output/runtime evidence, not local estimates.

Pass the future receipt with `--hosted-receipt`, `--hosted-receipt-sha256`, and
independent `--expected-commit`, `--expected-tree`,
`--expected-projection-sha256`, `--expected-output-sha256`,
`--expected-runtime-config-sha256`, plus the target bundle flags above. Exact
bindings and applicable limits are checked. Even a matching hosted receipt grants
no public activation authority; publicReadiness remains UNRUN in this report.
