# 09 — Admin login and the leads inbox

Type: AFK
Blocked by: 08

## Stories delivered
- As the store owner, I can log into an admin area and see every submitted plan as a
  row — unit type, item count, total, name, phone, timestamp — so that no lead is lost.
- As the store owner, I can open a lead and see its full itemised breakdown and the
  buyer's plan, so that I can pick up the phone already knowing what they want.

## Reviewable end state
Visit `/admin` while logged out and get bounced to a login. Log in with the shared
credentials. See a table of leads, newest first: buyer name, phone, unit type, item
count, total in VND, submitted-at. Click a row and see the full room-by-room itemisation
plus a link that opens the buyer's actual plan in the planner. Log out and confirm you
are locked out again.

## Reviewable end state — the access case
Hit the admin API endpoints directly with no session cookie and get 401s, not data.

## Notes
The lead inbox is the entire reason the app exists commercially, and it is deliberately
the last thing built — everything upstream has to work before a row here means anything.

**Auth is one shared login**, httpOnly session cookie, no user table, no roles, no
password reset, no invitations. Do not build user management. Credentials come from
environment configuration.

Vertical slice: admin auth dependency in FastAPI + `GET /api/admin/leads` and
`GET /api/admin/leads/{id}` + login route and the two admin screens in `app/(admin)/`.

Read-only. There is no lead status, no assignment, no notes field, no pipeline — those
are all post-v1 if they ever happen at all.

Take some care with the auth boundary: this is the only protected surface in the
product, so it is also the only place a mistake is expensive. Every admin endpoint goes
through one dependency, not per-route checks.

Test boundary: pytest — unauthenticated requests to every admin endpoint return 401;
a valid session reaches data; the list orders newest-first and paginates; lead detail
renders the frozen snapshot rather than recomputing from the live catalogue.
