import { useMemo } from 'react';
import { DoubleSide, FrontSide, Shape } from 'three';
import type { RoomShell } from '@/shared/api/types';
import { floorGrid, wallInwardNormal } from './room-presentation';

export function RoomShellMesh({ room, contactWallId }: { room: RoomShell; contactWallId: string | null }) {
  const walls = useMemo(() => room.walls.map(wall => {
    const normal = wallInwardNormal(room, wall);
    return { id: wall.id, lengthM: Math.hypot(wall.end[0] - wall.start[0], wall.end[1] - wall.start[1]), yaw: Math.atan2(normal[0], normal[1]), midpoint: [(wall.start[0] + wall.end[0]) / 2, (wall.start[1] + wall.end[1]) / 2] as const };
  }), [room]);
  const floor = useMemo(() => {
    const shape = new Shape(), [first, ...rest] = room.floorPolygon;
    shape.moveTo(first![0], first![1]);
    for (const point of rest) shape.lineTo(point[0], point[1]);
    shape.closePath();
    return shape;
  }, [room]);
  const grid = useMemo(() => floorGrid(room.floorPolygon), [room]);
  return <group name="room-shell">
    <mesh name="room-floor" rotation={[Math.PI / 2, 0, 0]} receiveShadow><shapeGeometry args={[floor]} /><meshStandardMaterial color="#cfc8bd" roughness={0.95} metalness={0} side={DoubleSide} /></mesh>
    {walls.map(wall => <mesh key={wall.id} name={wall.id} position={[wall.midpoint[0], room.ceilingHeightM / 2, wall.midpoint[1]]} rotation={[0, wall.yaw, 0]} receiveShadow><planeGeometry args={[wall.lengthM, room.ceilingHeightM]} /><meshStandardMaterial color={wall.id === contactWallId ? '#e8e2d6' : '#f2efe9'} roughness={1} metalness={0} side={FrontSide} /></mesh>)}
    <lineSegments name="room-floor-grid"><bufferGeometry><bufferAttribute attach="attributes-position" args={[grid, 3]} /></bufferGeometry><lineBasicMaterial color="#b3aa9c" /></lineSegments>
    {walls.map(wall => <mesh key={`${wall.id}-skirting`} position={[wall.midpoint[0], .04, wall.midpoint[1]]} rotation={[0, wall.yaw, 0]}><planeGeometry args={[wall.lengthM, .08]} /><meshStandardMaterial color="#e2dcd0" roughness={1} side={DoubleSide} /></mesh>)}
  </group>;
}
