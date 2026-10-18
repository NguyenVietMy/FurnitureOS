import type { CaptureDraft, OpeningDraft, SemanticOpening } from '@/shared/api/types';
import { walls } from './CapturePhotos';
export function OpeningEditor({draft,edit,disabled,proposals}:{draft:CaptureDraft;edit:(value:CaptureDraft)=>void;disabled:boolean;proposals:ReadonlyArray<SemanticOpening>}) {
  const openings=draft.openings??[];
  const update=(index:number,patch:Partial<OpeningDraft>)=>edit({...draft,dimensionsConfirmed:false,openings:openings.map((opening,i)=>i===index?{...opening,...patch}:opening)});
  const add=(proposal?:SemanticOpening)=>edit({...draft,dimensionsConfirmed:false,openings:[...openings,{
    id:crypto.randomUUID(),wallId:proposal?.wallId??null,kind:proposal?.kind??'unknown',distanceFromStartM:null,widthM:null,bottomM:null,heightM:null,
    clearanceDepthM:null,direction:proposal?.direction??'unknown',angle:proposal?.angle??'unknown',hingeSide:proposal?.hingeSide??'unknown',
    reviewed:false,evidenceIds:proposal?[proposal.id]:[]} ]});
  return <section><h2>Correct every Opening</h2><p>Add missed Openings, remove false proposals and correct wall/type/measurements. Distances start at the arrow on the plan. Unknown door operation blocks generation.</p>
    <fieldset disabled={disabled}><legend>Photo semantics to review</legend>{proposals.length?proposals.map((proposal,index)=><div key={index} className="proposal">
      <span>{proposal.kind} · {proposal.location} · {proposal.visibility} · swing {proposal.direction}/{proposal.angle}/{proposal.hingeSide}</span>
      <button type="button" onClick={()=>add(proposal)}>Add proposal to inventory</button></div>):<p>No complete inventory can be inferred from an empty proposal list. Review all walls explicitly.</p>}
    <button type="button" onClick={()=>add()}>Add missed Opening</button>
    {openings.map((opening,index)=><fieldset className="opening-fields" key={opening.id}><legend>Opening {index+1}</legend>
      <label>Opening wall <select aria-label={`Opening ${index+1} wall`} value={opening.wallId??''} onChange={event=>update(index,{wallId:(event.target.value||null) as OpeningDraft['wallId'],reviewed:false})}>
        <option value="">Unknown wall</option>{walls.map((wall,i)=><option key={wall} value={wall}>Wall {'ABCD'[i]}</option>)}</select></label>
      <label>Opening type <select aria-label={`Opening ${index+1} type`} value={opening.kind} onChange={event=>update(index,{kind:event.target.value as OpeningDraft['kind'],reviewed:false,direction:'unknown',angle:'unknown',hingeSide:'unknown',bottomM:event.target.value==='door'?0:null})}>
        <option value="unknown">Unknown</option><option value="door">Door</option><option value="window">Window</option></select></label>
      {([['distanceFromStartM','Distance from wall start'],['widthM','Width'],['bottomM','Bottom / sill height'],['heightM','Height'],['clearanceDepthM','Inward clearance']] as const).map(([key,label])=><label key={key}>{label} (m)
        <input aria-label={`Opening ${index+1} ${label}`} type="number" step="0.01" value={opening[key]??''}
          onChange={event=>update(index,{[key]:event.target.value===''?null:Number(event.target.value),reviewed:false})}/></label>)}
      {opening.kind==='door'?<>
        <label>Door direction <select aria-label={`Opening ${index+1} door direction`} value={opening.direction} onChange={e=>update(index,{direction:e.target.value as OpeningDraft['direction'],reviewed:false})}>{['unknown','inward','outward','sliding','other'].map(v=><option key={v}>{v}</option>)}</select></label>
        <label>Swing angle <select aria-label={`Opening ${index+1} swing angle`} value={opening.angle} onChange={e=>update(index,{angle:e.target.value as OpeningDraft['angle'],reviewed:false})}><option value="unknown">Unknown</option><option value="90">90 degrees</option><option value="other">Other</option></select></label>
        <label>Hinge side <select aria-label={`Opening ${index+1} hinge side`} value={opening.hingeSide} onChange={e=>update(index,{hingeSide:e.target.value as OpeningDraft['hingeSide'],reviewed:false})}><option value="unknown">Unknown</option><option value="start">Wall start end</option><option value="end">Wall end end</option></select></label>
      </>:null}
      <label className="check"><input type="checkbox" checked={opening.reviewed??false} onChange={e=>update(index,{reviewed:e.target.checked})}/>I reviewed this Opening and its operation.</label>
      <button type="button" onClick={()=>edit({...draft,dimensionsConfirmed:false,openings:openings.filter((_,i)=>i!==index)})}>Remove false Opening</button>
    </fieldset>)}
    <fieldset><legend>Complete inventory review</legend>{walls.map((wall,index)=><label className="check" key={wall}>
      <input type="checkbox" checked={draft.wallReviews?.includes(wall)??false} onChange={event=>edit({...draft,wallReviews:event.target.checked?[...(draft.wallReviews??[]),wall]:(draft.wallReviews??[]).filter(item=>item!==wall)})}/>
      I reviewed every Opening on Wall {'ABCD'[index]}, including if there are none.</label>)}</fieldset>
    </fieldset>
  </section>;
}
