import { describe, expect, it } from 'vitest';
import { Shape, ShapeGeometry } from 'three';
import { floorGrid, wallInwardNormal } from '../src/features/design/room-presentation';
import { activeWalls, draftWalls, wallLabel } from '../src/features/capture/capture-topology';
import type { CaptureDraft, RoomShell } from '../src/shared/api/types';
const points = [[-3,-2.5],[1,-2.5],[1,-.5],[3,-.5],[3,2.5],[-3,2.5]] as const;
const ids = ['wall-north','wall-notch-vertical','wall-notch-horizontal','wall-east','wall-south','wall-west'];
const room: RoomShell = { id:'hand-l',floorPolygon:points,ceilingHeightM:2.7,openings:[],walls:points.map((p,i)=>({id:ids[i]!,label:ids[i]!,start:p,end:points[(i+1)%6]!})) };
describe('L Room presentation', () => {
  it('uses actual winding and independently reversed wall directions', () => {
    const expected = [[0,1],[-1,0],[0,1],[-1,0],[0,-1],[1,0]];
    room.walls.forEach((wall,i)=>{
      expect(wallInwardNormal(room,wall).map(v=>v===0?0:v)).toEqual(expected[i]);
      expect(wallInwardNormal({...room,floorPolygon:[...points].reverse()},{...wall,start:wall.end,end:wall.start}).map(v=>v===0?0:v)).toEqual(expected[i]);
    });
  });
  it('clips every decorative grid segment out of the absent notch', () => {
    const positions = floorGrid(points);
    expect(positions.length).toBeGreaterThan(0);
    for(let i=0;i<positions.length;i+=6){
      for(const t of [0,.25,.5,.75,1]){
        const x=positions[i]!*(1-t)+positions[i+3]!*t, z=positions[i+2]!*(1-t)+positions[i+5]!*t;
        expect(x>1 && z<-.5).toBe(false);
        expect(x).toBeGreaterThanOrEqual(-3);expect(x).toBeLessThanOrEqual(3);
        expect(z).toBeGreaterThanOrEqual(-2.5);expect(z).toBeLessThanOrEqual(2.5);
      }
    }
  });
  it('triangulates exactly 26 square metres with no notch triangle', () => {
    const shape=new Shape();shape.moveTo(points[0][0],points[0][1]);points.slice(1).forEach(p=>shape.lineTo(p[0],p[1]));shape.closePath();
    const geometry=new ShapeGeometry(shape),p=geometry.getAttribute('position'),indices=geometry.index!;
    let area=0;
    for(let i=0;i<indices.count;i+=3){
      const a=indices.getX(i),b=indices.getX(i+1),c=indices.getX(i+2);
      area+=Math.abs((p.getX(b)-p.getX(a))*(p.getY(c)-p.getY(a))-(p.getY(b)-p.getY(a))*(p.getX(c)-p.getX(a)))/2;
      expect((p.getX(a)+p.getX(b)+p.getX(c))/3>1 && (p.getY(a)+p.getY(b)+p.getY(c))/3<-.5).toBe(false);
    }
    expect(area).toBe(26);geometry.dispose();
  });
  it('keeps the directed six-wall and rectangle labels stable and invalid drafts editable', () => {
    const draft: CaptureDraft={topology:'L-shaped',widthM:6,depthM:5,notchWidthM:2,notchDepthM:2,heightM:2.7};
    expect(draftWalls(draft)?.map(w=>w.length)).toEqual([4,2,2,3,6,5]);
    expect(draftWalls({...draft,notchWidthM:6})).toBeNull();
    expect(activeWalls('rectangle')).toEqual(['wall-north','wall-east','wall-south','wall-west']);
    expect(wallLabel('L-shaped','wall-east')).toBe('Wall D');
    expect(wallLabel('rectangle','wall-east')).toBe('Wall B');
    expect(draftWalls({...draft,topology:'rectangle',notchWidthM:900})?.map(w=>w.length)).toEqual([6,5,6,5]);
  });
});

