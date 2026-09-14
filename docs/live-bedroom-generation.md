# Live bedroom generation

The `/design/live-bedroom` flow sends one selected reference image to the
server. The server privately maps that image to an existing Style, filters the
provider-neutral Catalogue, and offers only eligible Product metadata, the
fixed 4 x 3 m bedroom Room Shell, its walls and derived Zones to the model.
The browser supplies only `roomType: bedroom` and a reference ID.

The model is fixed to `claude-opus-5` with adaptive thinking, high effort and
JSON Schema structured output. Its provider-only grammar is a strict `anyOf`
of seven operation objects: each variant requires only meaningful fields,
forbids additional fields, and uses literal operation and side values. It
selects Product IDs and coordinate-free Placement Intents. FastAPI retains the
full public PlacementIntent validation, normalizes neutral defaults only at
that internal boundary, validates the complete response, and freezes one
required bed at request ID `anchor-bed`, and derives optional policy by Product
category: rugs and lamps are decoration; nightstands, wardrobes, dressers and
chairs are secondary furniture. Repairs preserve the identity set, bed anchor
and category of every request.

The prompt lists compact exact Product/Room wall-operation tuples derived from
the authoritative corner and wall helpers; the same tuples reject unsupported
lamp/chair wall contact and back-only wardrobe corners before any solve. They
describe operation support, not whole-Design fit.

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
- `ANTHROPIC_API_KEY`, or `ANTHROPIC_CREDENTIAL_FILE` pointing to an external
  `.local` file
- optional `ANTHROPIC_WORKSPACE_ID`; when present its
  `anthropic-workspace-id` header is sent to model metadata, token count and
  Messages
- `FURNITUREOS_GENERATION_SPEND_CAP_USD=5`, matching the owner-authorized total
- `FURNITUREOS_GENERATION_ACCOUNTING_PATH`, outside the repository

The owner supplied the required workspace ID through the external credential
file. A free exact-model metadata request through this adapter passed and
confirmed `claude-opus-5`, a 1,000,000-token input context, image input,
structured output, adaptive thinking, and high effort. The host-owned paid
Messages probe also passed with the exact model, `end_turn`, schema-valid JSON,
the approved reference pixels, adaptive thinking, and high effort. It reported
3,028 input and 9 output tokens ($0.015365), settled in the shared ledger. The
archived first series and probe have settled USD 0.725615 in total. The owner
authorized a USD 5.00 total across all probes and generation tests, leaving
USD 4.274385 before the second-series work; the same external ledger must be
reused across them.
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
reserves all 8,192 output tokens, for USD 0.6048 maximum per attempt. This does
not rely on the count estimate and fits within the authorized USD 5 total.
Unknown usage retains that reservation. Reported usage above it is
persisted at the larger actual charge and prevents later calls.

This ledger is a hard local cap only for processes that share its locked file.
It is not an Anthropic account limit or a distributed ledger. Vercel Functions
have ephemeral local files, so live paid calls fail closed there until a
separately reviewed persistent accounting design exists. Local authorized
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
provider and solver identities. `freeze`
requires the owner image-set, predetermined-schedule, and USD 5 budget records.
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
outside this narrowed series. Exact-model metadata and the earlier minimal paid
capability probe are verified; the changed production-union probe and new
technical series remain host-owned and pending. Second-series aesthetics and
owner judgments are deferred. The physical-phone gate was
waived by the owner; it is recorded as `WAIVED`, never `PASSED`. Browser
instrumentation still measures, on one `performance.now()` clock, from receipt
of a parsed solved Design until every Placement's complete active LOD has
rendered through the main camera with all visible meshes and materials,
nontrivial screen/frustum coverage, and no asset error or texture fallback.
Shadow-camera and single-fragment callbacks cannot complete the measurement.
