import type { CaptureDraft } from '@/shared/api/types';
import { walls } from './CapturePhotos';
export function RoomReviewPreview({draft,confirmed}:{draft:CaptureDraft;confirmed:boolean}) {
  if(draft.topology && draft.topology!=='rectangle')return <section className="room-review"><h2>Unsupported Room shape</h2><p>Return to shape selection. This topology is not previewed as a bounding rectangle.</p></section>;
  const width=draft.widthM,depth=draft.depthM;
  const valid=Boolean(width&&width>0&&depth&&depth>0);
  const scale=valid?Math.min(340/width!,270/depth!):1;
  const w=valid?width!*scale:340,h=valid?depth!*scale:270;
  const left=(500-w)/2,top=(390-h)/2,right=left+w,bottom=top+h;
  return <section className="room-review"><h2>{confirmed?'Confirmed Room':'Room review preview'}</h2>
    <p>{valid?`${width} × ${depth} m · ceiling ${draft.heightM??'unknown'} m · ${draft.roomType||'Room Type unknown'}`:'Enter dimensions to inspect the Room scale. Wall labels below are schematic.'}</p>
    <svg viewBox="0 0 500 390" role="img" aria-label="Room plan with stable wall labels, start and end directions, Openings and door swings">
      <defs><marker id="wall-arrow" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto"><path d="M0 0 L6 3 L0 6" fill="#446bce"/></marker></defs>
      <rect x={left} y={top} width={w} height={h} fill="#fdfef6" stroke="#23211d" strokeWidth="3"/>
      <path d={`M${left+20} ${top-15} H${right-20} M${right+15} ${top+20} V${bottom-20} M${right-20} ${bottom+15} H${left+20} M${left-15} ${bottom-20} V${top+20}`} stroke="#446bce" fill="none" markerEnd="url(#wall-arrow)"/>
      <text x="250" y={top-28} textAnchor="middle">Wall A · start → end · {width??'?'} m</text>
      <text x={right+36} y="195" textAnchor="middle" transform={`rotate(90 ${right+36} 195)`}>Wall B · {depth??'?'} m</text>
      <text x="250" y={bottom+42} textAnchor="middle">Wall C · start ← end · {width??'?'} m</text>
      <text x={left-36} y="195" textAnchor="middle" transform={`rotate(-90 ${left-36} 195)`}>Wall D · {depth??'?'} m</text>
      {draft.openings?.map((opening,index)=>{
        const wall=walls.indexOf(opening.wallId as typeof walls[number]);
        const length=wall%2===0?width:depth;
        if(wall<0||!length||length<=0||!opening.widthM||opening.widthM<=0||opening.distanceFromStartM==null)return null;
        const ratio=opening.distanceFromStartM/length,span=opening.widthM/length;
        const x=wall===0?left+w*ratio:wall===2?right-w*ratio:wall===1?right:left;
        const y=wall===1?top+h*ratio:wall===3?bottom-h*ratio:wall===0?top:bottom;
        const dx=wall===0?w*span:wall===2?-w*span:0,dy=wall===1?h*span:wall===3?-h*span:0;
        const endHinge=opening.hingeSide==='end',hx=endHinge?x+dx:x,hy=endHinge?y+dy:y;
        const closedX=endHinge?x:x+dx,closedY=endHinge?y:y+dy;
        const r=Math.hypot(dx,dy),inward=[[0,1],[-1,0],[0,-1],[1,0]][wall]!;
        const openX=hx+inward[0]!*r,openY=hy+inward[1]!*r;
        const sweep=(closedX-hx)*inward[1]!-(closedY-hy)*inward[0]!>0?1:0;
        return <g key={opening.id}>
          {opening.kind==='door'&&opening.direction==='inward'&&opening.angle==='90'&&opening.hingeSide!=='unknown'?
            <path d={`M${hx} ${hy} L${closedX} ${closedY} A${r} ${r} 0 0 ${sweep} ${openX} ${openY} Z`} fill="#ff7b5520" stroke="#ff7b55" strokeDasharray="4 4"/>:null}
          <line x1={x} y1={y} x2={x+dx} y2={y+dy} stroke={opening.kind==='door'?'#ff7b55':'#46d7d4'} strokeWidth="9"/>
          <text x={x+(wall===1?-18:18)} y={y+(wall===0?25:-12)} fontSize="12">O{index+1}</text></g>;
      })}
      <text x="250" y="200" textAnchor="middle">{confirmed?'Confirmed rectangle':'Unconfirmed rectangle'}</text>
    </svg>
    <ol>{draft.openings?.map((opening,index)=><li key={opening.id}>Opening {index+1}: {opening.kind}, Wall {'ABCD'[walls.indexOf(opening.wallId as typeof walls[number])]??'unknown'} · start offset {opening.distanceFromStartM??'?'} m · width {opening.widthM??'?'} m · bottom {opening.bottomM??'?'} m · height {opening.heightM??'?'} m · clearance {opening.clearanceDepthM??'?'} m{opening.kind==='door'?` · ${opening.direction}/${opening.angle}° · hinge ${opening.hingeSide}`:''}</li>)}</ol>
  </section>;
}
