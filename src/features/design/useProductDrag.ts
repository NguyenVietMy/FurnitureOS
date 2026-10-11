import { useThree, type ThreeEvent } from '@react-three/fiber';
import { useEffect, useRef } from 'react';
import { Plane, Raycaster, Vector2, Vector3 } from 'three';
import type { Placement, Vec2 } from '@/shared/api/types';
import type { NudgeController } from './useNudge';

/** Native capture keeps the ray/plane drag alive after leaving the Mesh. */
export function useProductDrag(placement: Placement, nudge?: NudgeController) {
  const { gl, camera, controls } = useThree();
  const latest = useRef(nudge);
  latest.current = nudge;
  const active = useRef<{ id: number; offset: Vec2; release: () => void } | null>(null);
  const canvas = gl.domElement;
  const listening = Boolean(nudge?.enabled && nudge.instanceId === placement.instanceId);
  const plane = new Plane(new Vector3(0, 1, 0), -placement.position[1]);
  const planePoint = (event: PointerEvent): Vec2 | null => {
    const bounds = canvas.getBoundingClientRect();
    const pointer = new Vector2((event.clientX - bounds.left) / bounds.width * 2 - 1,
      -(event.clientY - bounds.top) / bounds.height * 2 + 1);
    const ray = new Raycaster();
    ray.setFromCamera(pointer, camera);
    const point = ray.ray.intersectPlane(plane, new Vector3());
    return point ? [point.x, point.z] : null;
  };

  useEffect(() => {
    if (!listening) return;
    const cleanup = () => { active.current?.release(); active.current = null; };
    const cancel = () => { if (!active.current) return; cleanup(); latest.current?.cancel(); };
    const otherPointer = (event: PointerEvent) => {
      if (active.current && event.pointerId !== active.current.id) cancel();
    };
    const move = (event: PointerEvent) => {
      const drag = active.current;
      if (!drag || drag.id !== event.pointerId) return;
      event.preventDefault();
      const point = planePoint(event);
      if (point) latest.current?.move([point[0] + drag.offset[0], point[1] + drag.offset[1]]);
    };
    const finish = (event: PointerEvent) => {
      if (!active.current || active.current.id !== event.pointerId) return;
      cleanup();
      latest.current?.end();
    };
    const lost = (event: PointerEvent) => { if (active.current?.id === event.pointerId) cancel(); };
    const escape = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      if (active.current) cancel(); else latest.current?.cancel();
    };
    canvas.addEventListener('pointermove', move);
    canvas.addEventListener('pointerup', finish);
    canvas.addEventListener('pointercancel', lost);
    canvas.addEventListener('lostpointercapture', lost);
    document.addEventListener('pointerdown', otherPointer, true);
    document.addEventListener('keydown', escape);
    return () => {
      cleanup();
      canvas.removeEventListener('pointermove', move);
      canvas.removeEventListener('pointerup', finish);
      canvas.removeEventListener('pointercancel', lost);
      canvas.removeEventListener('lostpointercapture', lost);
      document.removeEventListener('pointerdown', otherPointer, true);
      document.removeEventListener('keydown', escape);
    };
  }, [canvas, camera, placement.instanceId, listening]);

  useEffect(() => {
    if (!nudge?.enabled && active.current) { active.current.release(); active.current = null; }
  }, [nudge?.enabled]);

  return (event: ThreeEvent<PointerEvent>) => {
    const controller = latest.current;
    if (!controller || !placement.instanceId || event.button !== 0 || !event.isPrimary) return;
    const point = planePoint(event.nativeEvent);
    if (!point) return;
    if (!controller.begin(placement.instanceId)) {
      if (['idle', 'error', 'unavailable'].includes(controller.status)) controller.choose(placement.instanceId);
      return;
    }
    event.stopPropagation();
    event.nativeEvent.preventDefault();
    const cameraControls = controls as { enabled: boolean } | null;
    if (cameraControls) cameraControls.enabled = false;
    const id = event.pointerId;
    const release = () => {
      if (cameraControls) cameraControls.enabled = true;
      // Clear first: the resulting lost-capture event must not cancel a commit.
      active.current = null;
      if (canvas.hasPointerCapture(id)) canvas.releasePointerCapture(id);
    };
    active.current = { id, offset: [placement.position[0] - point[0], placement.position[2] - point[1]], release };
    canvas.setPointerCapture(id);
  };
}
