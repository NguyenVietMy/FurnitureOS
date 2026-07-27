# 08 — Submit the plan and get an itemised quote

Type: AFK
Blocked by: 05, 06

## Stories delivered
- As a buyer, I can submit my plan with my name and phone number and immediately see an
  itemised quote broken down by room, so that I get the number I just spent twenty
  minutes building.

## Reviewable end state
Furnish an apartment, click **Get my quote**, enter a name and phone number. Instantly
see a quote itemised room by room with quantities, unit prices and a grand total in VND,
plus a shareable link. Check the database: a lead row exists with the contact details, a
snapshot of the itemisation, and the plan token. No email is sent, no message fires,
nothing else happens.

## Reviewable end state — the security case
Tamper with the submitted total in the browser's network tools. The stored lead ignores
it entirely and shows the correct recomputed figure.

## Notes
This is the conversion event and the only moment identity is requested. Name and phone
are the only fields — no email, because nothing is ever emailed.

Vertical slice: `leads` table + `POST /api/quotes/{plan_token}` + the quote view.

**The server recomputes every price.** The lead's itemisation is built server-side from
the plan's item ids and quantities against the catalogue; the client's running total is
display-only and is never trusted or stored. This is the single most important rule in
the ticket.

The lead **snapshots** its itemisation at submission time, so a later catalogue price
change does not silently rewrite history on a quote you already discussed with a buyer.
Note the deliberate asymmetry with issue 05: a *plan* resolves prices live, a *lead*
freezes them.

Reuse `planTotals` from issue 06 for the buyer-facing view so the on-screen quote and
the stored lead cannot drift in structure.

Explicitly not in this ticket, and not coming: payment, checkout, deposits, stock holds,
delivery scheduling, email, SMS, WhatsApp, Zalo, PDF generation.

Test boundary: pytest at the service layer — a submitted total that disagrees with the
catalogue is ignored; itemisation groups correctly by room; the snapshot survives a
subsequent catalogue price change; submitting against an unknown or malformed plan
token 404s.
