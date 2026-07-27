"use client";

import { OrbitControls } from "@react-three/drei";
import { Canvas, useFrame } from "@react-three/fiber";
import { useMemo, useRef, type ReactNode } from "react";
import { MOUSE, Shape, type Mesh } from "three";

import { deriveWallPieces, occludesInterior, outlineCentroid } from "../geometry";
import type { Point, Unit } from "../types";
import { toPlan, toWorld, toWorldRotation } from "./coords";

const FLOOR_COLOUR = "#d9d2c7";
const WALL_COLOUR = "#f0ece6";

/**
 * The apartment shell, and whatever else belongs in the same canvas.
 *
 * `children` render inside the `<Canvas>`, which is how the plan module puts furniture
 * in the room without this module learning what furniture is. Anything passed in is
 * subject to the same camera, lights and controls as the walls.
 */
export function UnitScene({ unit, children }: { unit: Unit; children?: ReactNode }) {
  const centre = useMemo(() => outlineCentroid(unit.outline), [unit.outline]);
  const radius = useMemo(() => outlineRadius(unit.outline, centre), [unit.outline, centre]);

  return (
    <Canvas
      shadows
      camera={{
        // Off one corner and above, far enough back to hold the whole unit.
        position: toWorld([centre[0] + radius, centre[1] - radius], radius * 1.1),
        fov: 45,
        near: 0.1,
        far: 500,
      }}
    >
      <color attach="background" args={["#eef1f4"]} />
      <hemisphereLight intensity={1.1} groundColor="#b9b2a6" />
      <directionalLight position={[radius, radius * 2, radius]} intensity={1.6} castShadow />

      <Floor unit={unit} />
      <Walls unit={unit} interior={centre} />

      {children}

      <OrbitControls
        makeDefault
        target={toWorld(centre)}
        enableDamping
        minDistance={2}
        maxDistance={radius * 6}
        // Left drag is reserved for selecting and dragging furniture, so orbiting moves
        // to the right button.
        mouseButtons={{ LEFT: undefined, MIDDLE: MOUSE.DOLLY, RIGHT: MOUSE.ROTATE }}
        // Stop the camera dropping under the floor, where the unit is a silhouette.
        maxPolarAngle={Math.PI / 2 - 0.05}
      />
    </Canvas>
  );
}

function Floor({ unit }: { unit: Unit }) {
  const shape = useMemo(() => {
    const outline = new Shape();
    unit.outline.forEach(([x, y], index) => {
      if (index === 0) outline.moveTo(x, y);
      else outline.lineTo(x, y);
    });
    outline.closePath();
    return outline;
  }, [unit.outline]);

  // The shape is authored in the plan's XY; this rotation is what lays it into XZ, and
  // it is the same mapping `toWorld` applies.
  return (
    <mesh rotation={[-Math.PI / 2, 0, 0]} receiveShadow>
      <shapeGeometry args={[shape]} />
      <meshStandardMaterial color={FLOOR_COLOUR} />
    </mesh>
  );
}

function Walls({ unit, interior }: { unit: Unit; interior: Point }) {
  const pieces = useMemo(() => deriveWallPieces(unit), [unit]);
  const meshes = useRef<(Mesh | null)[]>([]);

  // Visibility changes every frame the camera moves. Setting `visible` on the meshes
  // directly keeps it out of React state — re-rendering the whole unit on mouse-move
  // would be a lot of work to arrive at the same picture.
  useFrame(({ camera }) => {
    const cameraPlan = toPlan(camera.position.x, camera.position.z);

    pieces.forEach((piece, index) => {
      const mesh = meshes.current[index];
      if (mesh) mesh.visible = !occludesInterior(piece, cameraPlan, interior);
    });
  });

  return (
    <group>
      {pieces.map((piece, index) => (
        <mesh
          key={`${piece.wallId}:${index}`}
          ref={(mesh) => {
            meshes.current[index] = mesh;
          }}
          position={toWorld(piece.center, (piece.base_m + piece.top_m) / 2)}
          rotation={toWorldRotation(piece.angle_rad)}
          castShadow
          receiveShadow
        >
          <boxGeometry
            args={[piece.length_m, piece.top_m - piece.base_m, piece.thickness_m]}
          />
          <meshStandardMaterial color={WALL_COLOUR} />
        </mesh>
      ))}
    </group>
  );
}

/** Distance from the centre to the furthest corner — how far back the camera must sit. */
function outlineRadius(outline: readonly Point[], centre: Point): number {
  const furthest = outline.reduce(
    (max, [x, y]) => Math.max(max, Math.hypot(x - centre[0], y - centre[1])),
    0,
  );
  return Math.max(furthest, 1);
}
