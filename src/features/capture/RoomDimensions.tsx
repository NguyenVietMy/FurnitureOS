import type { CaptureDraft } from '@/shared/api/types';
const dimensionNames={widthM:'Room width',depthM:'Room depth',heightM:'Ceiling height'};
export function RoomDimensions({draft,edit,disabled}:{draft:CaptureDraft;edit:(value:CaptureDraft)=>void;disabled:boolean}) {
  return <section><h2>Confirm actual dimensions</h2><p>Blank means unknown. Type measurements in metres, or review a supported reference estimate. The photo model never measures your Room.</p>
    <fieldset disabled={disabled}><legend>Final Room scale</legend><div className="dimension-grid">
      {([['widthM','Width (Wall A / C)'],['depthM','Depth (Wall B / D)'],['heightM','Ceiling height']] as const).map(([key,label])=><label key={key}>{label} (m)
        <input aria-label={label} type="number" step="0.01" value={draft[key]??''} onChange={event=>edit({...draft,[key]:event.target.value===''?null:Number(event.target.value),dimensionsConfirmed:false})}/>
        {draft.dimensionEvidence?.some(e=>e.field===key)?<span className="capture-warning">Provisional reference origin; verify or override.</span>:null}</label>)}
    </div>
    {draft.dimensionEvidence?.map((e,index)=><div className="evidence" key={index}><span>{dimensionNames[e.field]}: {e.valueM.toFixed(3)} m provisional evidence</span>
      <label>Manual override reason<input value={e.overrideReason??''} onChange={event=>edit({...draft,dimensionsConfirmed:false,dimensionEvidence:draft.dimensionEvidence?.map((item,i)=>i===index?{...item,overrideReason:event.target.value}:item)})}/></label>
      <button onClick={()=>edit({...draft,dimensionsConfirmed:false,dimensionEvidence:draft.dimensionEvidence?.filter((_,i)=>i!==index)})}>Remove unreliable measurement</button></div>)}
    <label className="check"><input type="checkbox" checked={draft.dimensionsConfirmed??false} onChange={event=>edit({...draft,dimensionsConfirmed:event.target.checked})}/>I checked and confirm all three final dimensions against the real Room.</label>
    </fieldset>
  </section>;
}
