import { useFrame, useThree } from '@react-three/fiber';
import { createContext, type ReactNode, useCallback, useContext, useLayoutEffect, useRef } from 'react';

const SceneFramesContext = createContext<() => void>(() => {});

/** Coalesce scene changes into a bounded settling sequence, then leave it idle. */
export function SceneFrames({ children }: { children: ReactNode }) {
  const invalidate = useThree((state) => state.invalidate);
  const remaining = useRef(0);
  const requestFrames = useCallback(() => {
    remaining.current = 4;
    invalidate();
  }, [invalidate]);
  // A React scene update, loaded Mesh or explicit camera move may need another
  // frame after Detailed selects its LOD and onAfterRender records real draws.
  // Requests coalesce rather than adding frames for every Product occurrence.
  useLayoutEffect(requestFrames);
  useFrame(() => {
    if (remaining.current > 0) {
      remaining.current -= 1;
      invalidate();
    }
  });
  return <SceneFramesContext.Provider value={requestFrames}>{children}</SceneFramesContext.Provider>;
}

export function useSceneFrames() {
  return useContext(SceneFramesContext);
}
