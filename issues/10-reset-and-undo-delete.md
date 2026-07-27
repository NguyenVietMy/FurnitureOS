# 10 — Reset a room, and undo an accidental delete

Type: AFK
Blocked by: 04

## Stories delivered
- As a buyer, I can undo an accidental delete, so that one misclick doesn't cost me my
  evening's work.
- As a buyer, I can reset a room to empty, so that I can start over deliberately.

## Reviewable end state
Delete a wardrobe. A toast appears — "Wardrobe removed · Undo" — and clicking it puts
the wardrobe back at exactly its previous position and rotation. Let the toast expire
and it is gone for good. Separately, hit "Reset room", confirm the dialog, and that room
empties while the rest of the apartment is untouched.

## Notes
Small ticket, disproportionate value: accidentally deleting something twenty minutes
into furnishing an apartment is the one loss that makes a buyer close the tab.

**This is not an undo stack.** A single-step delete-undo buffer on the `lib/plan`
reducer, and nothing more. General undo/redo history was explicitly rejected — do not
build a command pattern, do not snapshot state on every action.

Reset is scoped to a room, not the whole apartment, and always confirms.

Both are pure reducer work plus small UI, so this runs in parallel with anything after
issue 04.

Test boundary: Vitest on the reducer — undo restores exact pose and rotation, not an
approximation; a second delete replaces the buffered item rather than stacking; undo
after the buffer clears is a no-op; reset empties only the target room and leaves other
rooms' items and the grand total correct.
