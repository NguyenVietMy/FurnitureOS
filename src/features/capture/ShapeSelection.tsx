import type { CaptureDraft } from '@/shared/api/types';
export function ShapeSelection({draft,edit,disabled}:{draft:CaptureDraft;edit:(value:CaptureDraft)=>void;disabled:boolean}) {
  return <section><h2>Declare your Room</h2><fieldset disabled={disabled}><legend>Room Type</legend>
    <label><input type="radio" name="capture-room-type" checked={draft.roomType==='bedroom'} onChange={()=>edit({...draft,roomType:'bedroom',dimensionsConfirmed:false})}/> Bedroom</label>
  </fieldset><fieldset disabled={disabled}><legend>Room shape</legend>{['rectangle','L-shaped','other'].map(shape=><label key={shape}>
    <input type="radio" name="capture-shape" checked={draft.topology===shape} onChange={()=>edit({...draft,topology:shape,dimensionsConfirmed:false})}/>{shape==='rectangle'?'Rectangle':shape}</label>)}</fieldset>
    {draft.topology && !['rectangle','L-shaped'].includes(draft.topology)?<div role="alert" className="capture-warning">This topology is unsupported. It will not be replaced with a rectangle.
      <button onClick={()=>edit({...draft,topology:'',dimensionsConfirmed:false})}>Return to shape selection</button></div>:null}
  </section>;
}
