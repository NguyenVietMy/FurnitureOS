# 11 — "Open this on a computer" for phone visitors

Type: AFK
Blocked by: 02

## Stories delivered
- As a buyer on a phone, I see a clear "open this on a computer" page rather than a
  broken 3D canvas, so that I know what to do next.

## Reviewable end state
Open any buyer URL on a phone, or in device emulation, or with the browser window
dragged narrow. Instead of a stuttering or broken 3D scene, get a clean page explaining
this works on a laptop or desktop, showing the current URL in a copyable form, and
naming the showroom. Widen the window back and the app appears normally without a
reload.

## Notes
The product is desktop-only by decision, but the distribution plan is flyers, a QR code
in the shop window and Instagram — all of which are opened on phones. This page is the
seam between those two facts, so it is a real conversion surface, not an error state.
Write it as an invitation, not an apology.

Detect on coarse pointer plus viewport width, not on user-agent sniffing. Make it
reactive so resizing recovers without a reload.

The copyable URL matters: it is the only way a phone visitor can carry the link to a
computer, because nothing is ever emailed to them.

Blocked by 02 only because it needs the buyer routes to exist to guard.

Test boundary: a Playwright check at a phone viewport that the interstitial renders and
the 3D canvas does not mount; and that a desktop viewport mounts the app.
