# Local Product curator

This is an internal, Windows-only local workbench for re-reviewing exactly the
20 pinned ABO source identities. It does not grow or install the production
Catalogue by default. The historical Ticket 11 owner20 sample completed on
2026-10-19 (20 accepted, 575.715 active seconds); this checkout has not rerun it.
Ticket 12 genuine agent review accepted seven and rejected one candidate, followed by audited local promotion of three new identities alongside four reused Products. Independent source/seed inspection remains pending; optional owner evidence is UNRUN. Automated tests and native
pipeline proofs do not constitute owner judgments or commercial rights.

For the separate bounded living profile, `--actor agent --reviewer-id <identity>`
requires explicit `--profile living-seed-v1`, `--state-dir`, `--prepared-dir` and
`--port`. Its purpose/identity/evidence are immutable. Start/Resume reveals the
actual Meshes and frozen Style references; front/back/side and Large viewport
controls support inspection. Notes and explicit Living tags precede real native
acceptance. Pause after conversion settles; Finish freezes all final decisions.
Its report can become `COMPLETED_VALID_AGENT_REVIEW` while owner evidence stays
`UNRUN`. Controlled/test agent workspaces cannot escalate or promote. The
separate promotion CLI accepts `--actor agent --reviewer-id <same-identity>`;
dry-run first, inspect inventory/conflicts, then deliberate `--apply` locally.
Rejected candidates are omitted, with five accepted functional categories and
a common-Style sofa/table/chair trio still required. No owner workspace is reused.

Start from this checkout with its fresh npm dependencies and Python `.venv`:

```powershell
npm.cmd run curator
# Optional independent persistent directory and owned loopback port:
npm.cmd run curator -- --state-dir C:/path/to/fresh-external-state --port 4311
```

The default state directory is `%LOCALAPPDATA%/FurnitureOS/product-curator`.
The process binds **only 127.0.0.1**; the displayed numeric URL must be used.
An explicit state directory must be empty or carry this tool's ownership marker,
outside any Git checkout and dangerous roots, with no symlink/junction ancestors.
Main, this checkout, `public` and `dist` are never workspace targets. All owned
paths are checked again at use. This tool never recursively deletes runtime data.
Only this tool should write its owned directory; local filesystem write access
is trusted. An unrelated process with that access could replace files between
checks, so this is not an isolation boundary against a hostile local OS account.

The tool refuses hosted/CI and user-supplied `NODE_ENV=production` contexts. It
rejects `GLTFPACK_PATH` and `FURNITUREOS_ASSET_{SOURCE,WORK,TOOLS}_DIR` overrides.
UI compilation restores the caller's `NODE_ENV` before workers fork. There is
no production curator build/deploy command, app route, env flag, API route or
general static mount. Vite compiles a separate root into each external launch
directory with `publicDir: false`, `envDir: false`, and no development `/@fs` server.
Exact Host and same Origin checks cover all responses; cross-site requests and
CORS are rejected. JSON mutations additionally require a per-launch token,
16 KiB body limit, expected revision and stable operation ID. Metadata and Mesh
responses use `no-store`. BasisU's shipped Emscripten worker needs dynamic code;
the local CSP permits `unsafe-eval`, with script fetches restricted to this origin.

## Review and owner protocol

Before Start, only the protocol, input count/hash, optional remaining-candidate
estimate, and frozen UNRUN sample export are available. The ordered sample,
source hashes/byte counts and complete seed metadata are durably frozen at
initialization. Real owner timing starts **only** from Start owner sample.
Do not start a real owner workspace during automated validation.

The server owns NOT_STARTED → ACTIVE ↔ PAUSED → FINISHED. Uncertain active
server downtime/shutdown or backwards wall clock yields INVALID. Browser
disconnection leaves active wall time running. Pause is rejected while an
acceptance, validation or commit is active; wait for settlement, then explicitly
pause again. The serialized pause check and transition have no check/start gap.
While paused, preview/details unmount; server candidate/Mesh/decoder/Catalogue
reads and review mutations are denied. Already emitted bytes cannot be revoked.
A paused restart remains paused. Finished/invalid sample decisions are frozen;
their history and candidate review remain readable. To repeat an invalid sample,
retain/export it and choose a **new** external state directory.

All engine clock reads share an in-process observation watermark, including
status/report reads, progress, settlement and Finish verification/commit waits.
Normal polling updates memory only; existing durable events retain the watermark.
An observed ACTIVE rollback is latched immediately in read responses and durably
invalidated through the serialized state queue, even if the clock then recovers.
Pending async snapshots cannot restore valid timing. Active restart remains
invalid because in-process observations cannot survive downtime. INVALID history,
Mesh review and navigation remain available; decisions and timing stay frozen.

Active wall time includes tag review, rejects, converter waits, failed attempts,
retries and undo. Only explicit pauses are excluded. Finish requires 20 final
accept/reject decisions, no active attempt and no unresolved final acceptance.
The sample denominator is always 20; final unique validated Products determine
yield. Seconds per accepted Product is undefined (`null`) when none are accepted.
The remaining candidate count defaults to absent. A completed valid owner sample
can estimate remaining accepted yield and active time using sample rates, with
the 20-candidate denominator and selected re-review uncertainty prominently
recorded. Estimates are never labelled owner evidence before that completion.
Raw rejected/failed/retried/undo events remain in the JSON report. Controlled
owner-state tests persist `controlled-automated-owner-state`; even their FINISHED
exports are `ownerEvidenceStatus: UNRUN` and have no owner estimate.

Fresh Styles and Room Types are empty. Historical Styles are suggestions only.
Each atomic tag update is one undo step; accept/reject is one step. Navigation
persists but is never an undo target. Undo restores pre-action tags/decision/
selection and returns to the affected candidate, retaining all events and files.
Tag-only undo restores Styles/Room Types while preserving independent failed or
interrupted acceptance errors and retry eligibility.
Final decisions lock tags until undone. Accept requires at least one Style and
Room Type, rebuilds and independently validates, then advances to the next queue
position (wrapping after 20). Reject also advances. All-processed state retains
preview, navigation and undo. Navigation is permitted during conversion; tags,
decisions and undo wait for settlement. There is no cancellation control. Clean
shutdown waits for controlled work or interrupts the child; unacknowledged
acceptance is never inferred from an output directory after restart.

Shortcuts: A accept, R reject, U undo, [ / ] previous/next, 1–5 Styles, B bedroom,
L living room. Repeats/modifiers/editable/native action controls are ignored.
Checkbox Space and button Enter remain native. Focus the viewport for arrows
to orbit, +/− to zoom, 0 to reset; mouse orbit/zoom and buttons also work.
Readiness comes from the actual Mesh's `onAfterRender`, never a fetch or grid draw.
Preview failure/retry does not change tags or decisions. Dimensions are measured;
purchase availability is unknown, and ABO commercial licensing is unresolved.

## Transactions, retained files and recovery

`writer.lock` owns one state root. A live PID rejects a second server. A dead PID
lock is moved to a unique `stale-lock-*.json`, preserving it. PID reuse fails
closed: stop the old writer or inspect ownership manually, never kill an unknown
process. The journal consists of contiguous immutable numbered JSON snapshots,
each hash-chained to its predecessor with a monotonic revision and event. Every
file is written through an exclusive temporary file, fsynced and renamed on the
same volume before acknowledgement. POSIX also fsyncs the directory. Windows
uses file FlushFileBuffers and rename; this is process-crash recovery, not a
guarantee against device/power-loss behavior outside Node's filesystem API.

A durable `journal-initialized.json` identity marker lives outside the journal.
Missing/empty initialized journals, unmarked existing journals and interrupted
initialization fail closed; they are never silently treated as fresh state.
A corrupt checksum/version/identity, missing record, or incomplete `.pending`
write fails closed. Bad bytes are never silently reset/truncated. For recovery:
stop the writer; preserve a full external copy of the state and diagnostics;
inspect the contiguous checksum-valid prefix, pending record and referenced
attempts; obtain an explicit recovery decision. Use a new empty workspace for
fresh review. Do not delete or promote a pending record/attempt automatically.
An acknowledged acceptance must reopen, hash-match and independently validate
all its artifacts before startup/read. Undo does not exempt committed historical
outputs from verification. Missing or changed committed artifacts fail closed.

Each acceptance/retry gets a fresh UUID, durable input and append-only lifecycle.
One child worker runs at a time. It downloads the exact pinned source into that
attempt's own external source directory, verifies bytes and SHA256, and invokes
the same exported `buildProduct` implementation used by the existing CLI.
Explicit output/work directories must be new; no recursive reset is used.
The pinned Windows meshoptimizer v1.2 release archive is verified before extract;
native binary and archive hashes are rechecked on reuse. No tool/source cache is
borrowed from another checkout. A failed download/tool/conversion/validation/
metadata/commit leaves retained inputs, logs and staged bytes; retry uses a new
attempt. A corrupted cache is preserved and fails closed, never overwritten.

Independent validation reopens all files and verifies source/manifest identity,
raw-source bounds, floor-centre/metres/+Y/+Z with scale and yaw preserved, LOD
order/triangles/bounds, meshopt/BasisU, texture caps/mips/headers, safe paths/file
unions, and the strict <5,000,000 compressed-byte budget. Pydantic projects the
measured manifest with selected Room Types/private Styles through the existing
ABO adapter and `StaticCatalogue`. Only after validation does a durable acceptance
select one logical Product. A failed attempt never overwrites previous successful
files. Local Mesh URLs include immutable attempt UUIDs; original previews bind
the complete published-file inventory hash. The same URL never changes bytes.

## Verification commands

Set `CURATOR_EVIDENCE_DIR` to a new external evidence directory for every run.
Tests retain isolated automated/controlled-owner workspaces and never use a real
owner sample. Fixture conversion failures and copied published outputs are
explicitly labelled controlled, not native conversion. No environment variable
or HTTP parameter enables the injected fixture runner in the production CLI.

```powershell
npm.cmd run curator:typecheck
node --test tools/product-curator/tests/*.test.mjs
npx.cmd playwright test --config tools/product-curator/playwright.config.ts
node tools/product-curator/prove-pipeline.mjs --state-dir <fresh-external-dir> --product-id lamp-rivet-harper-brass
.venv/Scripts/python.exe -m pytest backend_tests
npm.cmd run api:types
npm.cmd run typecheck
npm.cmd test -- --run
npm.cmd run assets:report
npm.cmd run build
node tools/product-curator/verify-production-exclusion.mjs
npm.cmd run test:e2e
git diff --check
```

For this ticket's entirely external ordinary/measurement browser evidence, use
the equivalent wrapper below. It invokes the same root Playwright config and
test filters, from an external working directory so the legacy landing captures
also stay outside source; it records every command/exit and restores normal dist.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tools/product-curator/prove-regressions.ps1 -EvidenceDir <fresh-external-dir>
node tools/product-curator/freeze-source.mjs --baseline <BASELINE.json> --plan <PLAN.md> --out <new-external-manifest.json>
```

The bounded real proof accepts exactly the approved lamp through HTTP after
default `createCurator`/`buildUI`, checks worker inheritance and selected neutral
Catalogue filtering, and retains actual input/source/native/output/implementation
hashes. It performs no bulk build. Ordinary e2e uses the existing controlled
measurement build and restores normal dist afterward; point its evidence env
and output directory outside source. Ticket 12 genuine agent review and local promotion are complete; optional human seed evidence remains UNRUN. Ticket 11 owner20 completed historically. Physical
phone/manual calibration is waived; actual-room-photo accuracy and paid-provider
checks remain DEFERRED_UNRUN until END OF PROJECT.
