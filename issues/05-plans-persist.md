# 05 — Plans persist to a private, unguessable URL

Type: AFK
Blocked by: 03

## Stories delivered
- As a buyer, my plan saves itself to a private link I can bookmark or send to my
  partner, so that I don't lose it and don't have to sign up.

## Reviewable end state
Furnish a room, watch the URL become `/plan/<token>`, then hard-refresh — everything is
still there. Copy the URL into a different browser and the same plan loads. Change one
character of the token and get a 404, not an error page that reveals whether the plan
exists.

## Notes
Replaces the prototype's `localStorage` entirely. The server is the source of truth.

Vertical slice: `plans` table (token, unit slug, payload JSON, created/updated
timestamps) + `POST /api/plans`, `GET /api/plans/{token}`, `PUT /api/plans/{token}` +
debounced autosave wired into the `lib/plan` reducer + the `/plan/<token>` route.

- Token generated with `secrets.token_urlsafe`. Knowing the URL *is* the
  authorisation — there is no buyer auth in v1 and none is coming.
- Autosave on a debounce, not on every pointer move.
- The payload stores item ids, poses and quantities — **never prices**. Prices are
  always resolved from the catalogue, so a plan made today reflects today's prices when
  reopened. This also matters for issue 08's server-side recompute.
- The server validates referential integrity (unit exists, item ids exist) but does not
  re-validate geometry, per the PRD.

Can be built in parallel with issue 04 — they touch different modules.

Test boundary: pytest at the service layer against a real Postgres test database.
Cover: token unguessability, wrong-token 404, unknown item id rejected, round-trip
save/load fidelity.
