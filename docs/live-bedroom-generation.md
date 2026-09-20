# Live bedroom generation

The `/design/live-bedroom` flow sends one selected reference image to the
server. The server privately maps that image to an existing Style, filters the
provider-neutral Catalogue, and offers only eligible Product metadata, the
fixed 4 x 3 m bedroom Room Shell, its walls and derived Zones to the model.
The browser supplies only `roomType: bedroom` and a reference ID.

The frozen generation configuration is `ticket-6-generation-config-v9`.
Earlier configuration and paid-probe bindings are historical after this
source and live-selection-scope change and cannot authorize a new series.

The model is fixed to `claude-opus-5` with adaptive thinking, high effort and
JSON Schema structured output. Its provider-only grammar is a strict `anyOf`
of seven operation objects: each variant requires only meaningful fields,
forbids additional fields, and uses literal operation and side values. It
states the atomic `flanking` invariant directly: exactly two distinct requests
with one shared reference and gap, one left and one right. A compact paired
example is explicitly grammar-only. One lone related Product uses one
`adjacent_to` request instead. The generic placement grammar remains broader
than this live stage.

For the current technical-validity stage, the model receives only the
Style-eligible beds and rugs and must return exactly one eligible bed plus zero
or one eligible rug. FastAPI enforces `bed-plus-optional-rug-v1` on initial and
repair drafts: another bed, a second rug, any other Product category, or repair
identity expansion is rejected as a typed correction and is never silently
filtered into a success. The broader Catalogue and arrangement engine remain
available to non-live callers and their direct regressions; there is no wider
live-generation bypass. This stage measures bed/rug technical validity, not a
complete furnishing or owner-aesthetic pass.

The model selects Product IDs and coordinate-free Placement Intents. FastAPI retains the
full public PlacementIntent validation, normalizes neutral defaults only at
that internal boundary, validates the complete response, and requires one bed
at request ID `anchor-bed`; the optional rug keeps the existing decoration
policy. Repairs preserve the identity set, the bed's exact
Product ID and every request's Product category. The live session alone permits
the bed's coordinate-free spatial Intent to change; it re-solves containment,
collisions, Openings, access and circulation, and never drops the bed or a
required dependency. Public Arrangement callers retain immovable required and
anchor Intents unless they explicitly use the internal repositioning policy.

The prompt lists compact exact Product/Room wall-operation tuples derived from
the authoritative corner and wall helpers; the same tuples reject unsupported
lamp/chair wall contact and back-only wardrobe corners before any solve. They
describe operation support, not whole-Design fit. Before the first provider
call, a bounded server preflight also classifies coordinate-free bed wall
options through the ordinary placement authority. A checked option is labelled
`witnessed-valid`, `conclusively-invalid`, or `unknown-bounded-search`; only the
first is positive evidence, and it is explicitly a bed-only witness rather
than a complete furnished-Design guarantee. The preflight tries at most 32
options and is cached only against the complete Catalogue version, Room, Zone,
eligible Product, capability, solver-limit and clearance inputs. Repair prompts
include the actual complete-Design status and identify `adjacent_to`/`flanking`
gaps that are smaller than the referenced Product's required access depth.
After a graph-valid selected-Design failure, the server may also spend one
shared budget of at most 32 private authority probes: at most 16 examine
coordinate-free variants over the changed requests or the selected protected
anchor's admitted spatial poses, every transitive dependent,
each affected atomic flanking group and the ancestor chain needed to solve that
scope. An anchor included as graph context does not pull in unrelated optional
children. A repair prompt repeats the bed-option table only for the identity-locked
selected anchor Product; the initial prompt still presents every eligible bed.
The remaining probes test complete combinations. Every probe retains the 256-candidate placement cap,
0.60 m circulation rule, Room/Openings/access checks, exact IDs and Product
identities. The gap ladder is derived from the current gap, required-access
depth and 0.1 m solver step; it is not a universal 0.70 m rule. Pair witnesses
are labelled pair-only. Only a successful solve and circulation check over the
entire selected bed/rug identity set becomes a complete-Design witness for
this stage. Bounded
failures remain unknown unless the underlying authority itself is exhaustive.
The compact guide is capped at 8 KiB, contains no coordinates or raw model
text, and is advisory in the next existing correction prompt. The provider's
reply still re-enters normal validation and solve history. Diagnostic probes
cannot publish success, consume provider calls, count as Arrangement attempts,
unlock drops, or rewrite a draft.

One `ArrangementSession` evaluates accepted selections in chronological order.
A structured selection rejected by server shape, graph, Product capability or
immutable repair policy may be corrected within the same three-call ceiling.
Rejected drafts create no solve and, before the first accepted selection, no
session or immutable identity. Later correction prompts keep the original
identity and actual valid solver history separate from typed, sanitized
correction feedback. Transport, HTTP, deadline, budget, model, stop-reason and
unparseable protocol failures remain terminal. Optional drops begin only after
an initial plus two actual valid failed repairs; exhausting calls sooner returns
an explicit failure with no drops. The global ceiling is three provider calls and 23
arrangement solves; each solve retains the existing 20-request and
256-candidate limits. The fixed Room's Zone offer is derived once per live
generation, then reused by provider graph validation, the arrangement session,
and the internal solver for both initial and repaired `in_zone` intents.

## Server configuration and cost boundary

Real calls require all of the following server-only configuration:

- `FURNITUREOS_LIVE_GENERATION_ENABLED=1`
- `ANTHROPIC_API_KEY` and `ANTHROPIC_WORKSPACE_ID`, or
  `ANTHROPIC_CREDENTIAL_FILE` pointing to an external `.local` file containing
  both values. File and direct overrides cannot be combined.
- `FURNITUREOS_GENERATION_SPEND_MODE=uncapped` for the owner-authorized local
  uncapped mode, with `FURNITUREOS_GENERATION_SPEND_CAP_USD` absent. Legacy
  callers may instead select `capped` and provide a finite positive cap no
  greater than USD 5.
- `FURNITUREOS_GENERATION_ACCOUNTING_PATH`, outside the repository

The owner bound the current external credential workspace to
`wrkspc_019rVhsM2NsARG8nwTd1G9hm`; stale direct key or workspace overrides fail
closed instead of silently choosing another account. A free exact-model
metadata request through the adapter passed and confirmed `claude-opus-5`, a
1,000,000-token input context, image input, structured output, adaptive
thinking, and high effort. Earlier paid probes and trials are historical for
their exact frozen prompts. The two pre-fix FIX-4 diagnostics brought the
version-1 ledger's committed amount to USD 7.417730, including one conservative
unknown-use hold. The owner subsequently authorized explicit uncapped local
accounting without changing provider billing or auto-reload. The builder does
not migrate the shared ledger or make paid calls; the host performs the
version-1-to-version-2 transition only after inspection.
Credentials never use a `VITE_`
variable. `.env*.local` is ignored, but external credential storage remains the
preferred boundary.

There are no automatic retries, redirects, fallback models or premium Fast
mode. Connect timeout is at most 10 seconds, every HTTP request has a genuine
90-second wall-clock watchdog, the full generation has a 300-second deadline,
and response bodies stop at 1 MiB. Prompt text, reference bytes, provider schema,
counted input and output tokens are bounded. The token-count endpoint receives
the model, complete messages/image, thinking, effort and structured-output
schema; it omits Messages-only `max_tokens`, which the real count endpoint
rejects as an extra input. Its estimate is not trusted as a billing cap:
the serialized request is capped at 786,432 bytes, with at most 32 KiB each of
prompt and transformed schema. The immutable JPEG is decoded and checked at
at most 400,000 bytes, 1800 x 1200 pixels, and 2,795 visual tokens. Anthropic's
[vision contract](https://platform.claude.com/docs/en/build-with-claude/vision)
defines one visual token per 28 x 28 patch. The ledger independently reserves
80,000 input tokens: both bounded UTF-8 text regions, the image patches, and
more than 11,000 tokens of fixed framing/schema overhead and headroom. It also
reserves all 8,192 output tokens, for a USD 0.6048 conservative charge record
per attempt. This does not rely on the count estimate. Unknown usage retains
that record. Reported usage above it is persisted at the larger actual charge
and prevents later calls in both accounting modes.

Version 2 records `accountingMode` and uses JSON `null` for `capUsd` in explicit
uncapped mode; it never encodes Infinity, NaN, or a substitute huge cap. A
version-1 USD 10 ledger migrates atomically on the first host-owned operation,
preserving every historical reservation and committed amount and recording its
origin. Capped mode continues to serialize reservations under a locked shared
file and enforce its chosen cap. Uncapped mode omits only that aggregate
comparison: it keeps reservations, settlements, unknown holds and overrun
fail-closed behavior. Neither mode is an Anthropic account limit or a
distributed ledger. Vercel Functions have ephemeral local files, so live paid
calls fail closed there until a separately reviewed persistent accounting
design exists. Local authorized
account probes use `scripts/provider_probe.py`. The `production-export` mode
binds the exact final prompt, strict union schema, reference pixels,
model/settings and current source without loading provider settings or making a
call. `production-message` uses those same bytes through the real adapter and
validates the response with the same server rules; it requires
`--allow-paid-message` and is host-only. Both write only sanitized evidence
outside the repo. The earlier minimal-schema probe does not establish
acceptance of this changed production union.

## Evidence and current human gates

`scripts/ticket6_evidence.py prepare` records exact source/build, Product asset,
runtime decoder, bundled Catalogue-provider manifest, Room, complete Product
and private eligibility metadata for every reference, per-reference prompt,
provider and solver identities. `freeze` requires the exact owner image-set,
predetermined schedule, FIX-5 authorization, current workspace, version-2
uncapped ledger and a current exact production-message binding. The ledger
must be the authorized shared path and retain, byte-for-byte and in order, both
the owner-bound historical reservations and the inspected post-diagnostic
version-1 baseline. Migration metadata is derived from that verified lineage;
an empty, substituted, truncated, reordered or retrospectively edited history
is rejected. Later reservations and settlements may be appended, while every
current formal-evidence audit rechecks the preserved final-freeze prefix and
recomputes the committed total from reservation status and usage.

A preliminary builder freeze records both historical version-1 identities
without changing the real ledger, but remains ineligible for a real series
until the host migration, probe and independent inspection are complete.
`append-run` recomputes that complete configuration before every append and
accepts exactly the next scheduled result, including failed calls, complete
solved Designs and screenshots. It rejects mixed freezes, reordered history,
drifted screenshots and source/build/configuration/runtime-deliverable drift.
A claimed-valid result is parsed as the full `SolvedDesign`, checked for
non-empty aligned identities, bound to the frozen Room/Zones/Catalogue and
reference eligibility, and replayed through authoritative placement and
circulation validation. Summaries also require the current candidate to match
the freeze, so archived records are not silently reinterpreted after source or
input drift.

Owner judgments are recorded later in a separate append-only log with
`append-judgment`. Owner `no` is accepted for any recorded outcome, including a
failed or invalid one; owner `yes` is accepted only for a valid solved Design.
All ten outcomes require an explicit yes/no judgment before `complete` or
`qualityGatePassed` can be true. The run input/record fields are unchanged for
the host mapper. The judgment record shape is unchanged, but its acceptance
rule now covers negative judgments on failed/invalid outcomes. Summary
`ownerPending` is the full ten-outcome denominator minus recorded judgments,
and `complete` now means ten runs plus ten judgments.

`technical-summary` is a separate validity-first result. It can pass only for
the complete predetermined ten-run series when all ten retained Designs are
server-valid and a freeze-bound render-evidence record marks all ten as valid.
It never supplies or infers aesthetic owner judgments; the existing owner
summary still requires explicit judgments and the separate 7/10 gate.

The six imported reference byte hashes, provenance, private mappings, and exact
second-series schedule are owner-approved. That schedule is `ref-01` five
times followed by `ref-06` five times. All six references remain available and
unchanged. Ref-05's known zero-call no-bed failure remains a regression but is
outside this narrowed series. Exact-model metadata and earlier prompt-specific
paid probes remain historical; the changed production prompt's smoke checks
and new five-plus-five technical series remain host-owned and pending after
independent inspection. Aesthetics and owner judgments are deferred. The
physical-phone gate was
waived by the owner; it is recorded as `WAIVED`, never `PASSED`. Browser
instrumentation still measures, on one `performance.now()` clock, from receipt
of a parsed solved Design until every Placement's complete active LOD has
rendered through the main camera with all visible meshes and materials,
nontrivial screen/frustum coverage, and no asset error or texture fallback.
Shadow-camera and single-fragment callbacks cannot complete the measurement.
