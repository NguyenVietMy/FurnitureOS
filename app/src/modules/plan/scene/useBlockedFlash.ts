"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/** Long enough to read as a refusal, short enough not to sit there nagging. */
const FLASH_MS = 450;

/**
 * "You cannot put it there", said in the scene rather than in a message box.
 *
 * A drag that is refused has to answer the buyer in the place they are looking, which
 * is the item under their pointer. One item flashes at a time — a second refusal moves
 * the flash rather than stacking another one — and it fades on its own, because a
 * blocked drag is a moment, not a state to be cleared.
 *
 * Repeated calls while a drag stays blocked hold the flash on: the timer restarts, so
 * the colour lasts as long as the pointer keeps pushing and clears shortly after.
 */
export function useBlockedFlash(): [string | null, (key: string) => void] {
  const [flashing, setFlashing] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const flash = useCallback((key: string) => {
    setFlashing(key);
    if (timer.current !== null) clearTimeout(timer.current);
    timer.current = setTimeout(() => setFlashing(null), FLASH_MS);
  }, []);

  // A flash outliving the canvas would set state on an unmounted tree.
  useEffect(() => {
    return () => {
      if (timer.current !== null) clearTimeout(timer.current);
    };
  }, []);

  return [flashing, flash];
}
