# Progressive Variants

Both live routes and confirmed Rectangle/L Captures use `POST …/variants`.
The response is bounded NDJSON: `shell`, labelled `progress`, `variant`, then
`complete`. Recoverable generation failure has an `error` before completion.
`VariantStreamEvent` is the OpenAPI/generated TypeScript contract. Legacy
`…/generate` JSON endpoints keep their existing single-Design behavior.

The shell precedes provider work. One request-local conversation retains the
initial image, Room, Catalogue, policy and schema, ordered assistant selections,
correction feedback and actual server-solved Placements. Final optional drops
include removed request/Product identities and Arrangement history. Client
mutations never rewrite this generation history. Private context is not logged
or cached in a process-global prompt cache.

A gets one candidate; B/C each get two, with one duplicate retry. A candidate
keeps the existing three-call repair ceiling and required anchor locks. The
whole batch allows at most five candidates/fifteen provider attempts. A physical
failure ends remaining work and retains already usable Variants. Duplicate
exhaustion explicitly offers fewer. Signatures hash a sorted multiset of Product
ID, metre position quantized to 1 cm, and normalized yaw quantized to 1 degree.
Half steps round away from zero; full rotations wrap. Instance IDs, order,
metadata and user mutations are excluded; repeated Products retain multiplicity.

Work has 270 seconds within the existing 300-second Capture lease ceiling.
Capture expiry may shorten it. Guards run before provider I/O, geometry and
circulation solves, and registration, and after blocking work. Persisted owner,
revision and confirmed Room hash authority is asserted around registration and
immediately before wire emission. Unpublished sessions are revoked on failure.
That wire assertion includes structured failures with derived Zones and terminal
completions. Work cutoff retains A only after final authority succeeds; actual
Capture invalidation emits a sanitized error and empty failed completion.
Each ready Variant owns a separate owner-bound Swap/Nudge session. The worker
stops with an explicit partial/failure outcome if registration is unavailable;
an unmanaged Variant is never emitted. The worker
holds its lease until it cannot publish; disconnect sets a shared cancellation
guard. A bounded in-flight provider call can finish, but cannot start subsequent
solve/publication work. SQL can reject release after Capture expiry/deletion;
the existing persisted lease then expires without renewal. No migration is used.
The 300-second response ceiling also bounds authority awaits and stalled sends.
If it cuts an already-started response, the client reports interruption and
retains ready Variants; it never treats EOF as successful completion.

An explicit ephemeral breakpoint ends the stable initial content. This configures
caching; it does not guarantee a hit. Five-minute writes cost 1.25 times normal
input and reads cost 0.1 times input for the retained model. See the
[provider caching contract](https://platform.claude.com/docs/en/build-with-claude/prompt-caching).
Absent counters remain unknown, measured zero remains zero, and totals are only
summed when complete. Unknown cache cost retains its full spend reservation.
Conversations allow 96 KiB text, 32 messages, the existing 32 KiB schema and
bounded reference JPEG, inside the existing 768 KiB serialized request cap.
Their independent 160,000-token input reservation includes framing headroom and
the write premium ($1.2048 maximum including 8,192 output tokens). Legacy calls
retain their 80,000-token reservation. A byte/context limit fails explicitly;
actual solved state is never truncated. Events cap at 512 KiB, client streams
at 4 MiB/32 events; EOF without completion is interrupted. There is no reconnect.

The client renders one selected canvas. A remains usable as B/C arrive. Keyboard
buttons expose pending/ready/unavailable states and a polite stage status; motion
is unnecessary. Controls sit directly below the displayed Room; Generate and
selection reveal that Room without smooth motion. Variant changes reset transient
operations. Batch keys, session IDs and monotonic mutation versions reject stale
callbacks. Accepted commits update their matching cached session across visits,
so returning to A reflects a commit that completed during A → B → A.
Stop retains ready results. Private draft, topology, Room Type, reference,
account and navigation invalidation aborts and clears private output.

## Evidence and frozen future timing protocol

Local controlled tests establish sequencing, geometry, authority and UI behavior.
They establish no real provider timing, model quality or measured cache hits.
Actual-photo AI and all paid proof remain **DEFERRED TO PROJECT END / UNRUN**.
Physical-phone and manual-calibration validation remain **WAIVED**, not passed.
The native tracker blockers #9/#12 remain open; this work changes no tracker state.

Protocol `ticket-14-live-timing-v1` freezes five sequential runs **per Room Type**
(ten batches), reference `ref-01`, model `claude-opus-5`, adaptive thinking/high
effort, current Catalogue/solver configuration and exact source fingerprint.
Use Chromium, 390×844 viewport, reduced motion, 150 ms latency, 9 Mbps download,
1 Mbps upload, a new browser context per run, and the same server instance.
Record the machine/OS/browser/server configuration, network condition, source
fingerprint, click timestamp, first fully furnished A frame timestamp, batch
outcome and actual cache read/write counters. The timing gate requires every
run to succeed under 30,000 ms; unknown counters are not zero. Do not discard
failed runs or automatically retry. Emulation does not undo the physical-phone waiver.

After separate owner authorization, prepare an external config with `protocol`,
`baseUrl`, `machine`, `referenceId: "ref-01"`, `serverSourceSha256` (the collector's
SHA256 of ordered JSON `{path,sha256}` source records) and the frozen configuration.
Run from the reviewed source:

```powershell
node scripts/measure-variants.mjs --authorized-paid --config C:/external/frozen.json --output C:/external/live-runs
```

This command initiates paid work and was not executed for Ticket 14 local proof.
Its collector and the standalone `scripts/variants_controlled_server.py` are
development tools, absent from the production frontend package. Runtime outputs,
traces and screenshots belong outside Git under `FURNITUREOS_EVIDENCE_DIR`.
The collector observes a bounded clone of the actual browser UI fetch, including
terminal usage, without DevTools response-body storage or another generation
request. Output requires a new external directory and exclusive files. Each run
has a start receipt and a final record even on collection/transport failure.
