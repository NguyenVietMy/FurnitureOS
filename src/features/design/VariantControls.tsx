import type { useVariants } from './useVariants';
import { useLayoutEffect, useRef } from 'react';
export function VariantControls({ flow }: { flow: ReturnType<typeof useVariants> }) {
  const { state } = flow;
  const selectedButton = useRef<HTMLButtonElement>(null);
  useLayoutEffect(() => {
    if (state.visit > 0) selectedButton.current?.focus({ preventScroll: true });
  }, [state.visit]);
  if (state.status === 'idle') return null;
  return <section className="variant-controls" aria-label="Design Variants">
    <div role="group" aria-label="Select Variant">{(['A', 'B', 'C'] as const).map(label => {
      const ready = !!state.variants[label];
      return <button key={label} ref={state.selected === label ? selectedButton : undefined} type="button" aria-pressed={ready && state.selected === label} disabled={!ready} onClick={() => flow.select(label)}>
        Variant {label} · {ready ? 'Ready' : flow.running ? 'Pending' : 'Unavailable'}
      </button>;
    })}</div>
    <p role="status" aria-live="polite">{state.message}</p>
    {flow.running ? <button type="button" onClick={flow.stop}>Stop generation</button> : null}
  </section>;
}
