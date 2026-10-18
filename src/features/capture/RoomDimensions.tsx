import type { CaptureDraft } from '@/shared/api/types';
import { dimensionFields } from './capture-topology';
const dimensionNames = { widthM: 'Overall width', depthM: 'Overall depth', heightM: 'Ceiling height', notchWidthM: 'Notch width', notchDepthM: 'Notch depth' };
export function RoomDimensions({ draft, edit, disabled, measurementsUnsaved }: { draft: CaptureDraft; edit: (value: CaptureDraft) => void; disabled: boolean; measurementsUnsaved: boolean }) {
  const fields = dimensionFields(draft.topology);
  return <section><h2>Confirm actual dimensions</h2>
    <p>Blank means unknown. Type measurements in metres, or review a supported reference estimate. The photo model never measures your Room.</p>
    {draft.topology === 'L-shaped' ? <p>The notch is the absent top-right corner. Both notch dimensions must be smaller than the corresponding overall dimension. Wall A + C = E; Wall B + D = F.</p> : null}
    <fieldset disabled={disabled}><legend>Final Room scale</legend><div className="dimension-grid">
      {fields.map(key => {
        const label = draft.topology === 'rectangle' && key === 'widthM' ? 'Width (Wall A / C)' : draft.topology === 'rectangle' && key === 'depthM' ? 'Depth (Wall B / D)' : dimensionNames[key];
        const notchInvalid = key === 'notchWidthM' ? draft.notchWidthM != null && draft.widthM != null && draft.notchWidthM >= draft.widthM : key === 'notchDepthM' ? draft.notchDepthM != null && draft.depthM != null && draft.notchDepthM >= draft.depthM : false;
        const invalid = draft[key] != null && (!Number.isFinite(draft[key]) || draft[key]! <= 0 || draft[key]! > 1000 || notchInvalid);
        return <label key={key}>{label} (m)<input aria-label={label} aria-invalid={invalid} aria-describedby={invalid ? `error-${key}` : undefined} type="number" step="0.01" value={draft[key] ?? ''} onChange={event => edit({ ...draft, [key]: event.target.value === '' ? null : Number(event.target.value), dimensionsConfirmed: false })} />
          {invalid ? <span id={`error-${key}`} className="capture-warning">{notchInvalid ? 'Leave a positive Room arm: reduce this notch dimension.' : 'Enter a positive finite value no greater than 1000 m.'}</span> : null}
          {draft.dimensionEvidence?.some(e => e.field === key) ? <span className="capture-warning">Provisional reference origin; verify or override.</span> : null}</label>;
      })}
    </div>
      {draft.dimensionEvidence?.filter(e => fields.includes(e.field)).map((e, index) => <div className="evidence" key={`${e.photoId}-${e.field}-${index}`}><span>{dimensionNames[e.field]}: {e.valueM.toFixed(3)} m provisional evidence</span>
        <label>Manual override reason<input value={e.overrideReason ?? ''} onChange={event => edit({ ...draft, dimensionsConfirmed: false, dimensionEvidence: draft.dimensionEvidence?.map(item => item === e ? { ...item, overrideReason: event.target.value } : item) })} /></label>
        <button onClick={() => edit({ ...draft, dimensionsConfirmed: false, dimensionEvidence: draft.dimensionEvidence?.filter(item => item !== e) })}>Remove unreliable measurement</button></div>)}
      {measurementsUnsaved ? <p role="status">Save Room details before confirming measurements and reviewing the Opening inventory.</p> : null}
      <label className="check"><input type="checkbox" disabled={measurementsUnsaved} checked={draft.dimensionsConfirmed ?? false} onChange={event => edit({ ...draft, dimensionsConfirmed: event.target.checked })} />I checked and confirm all {fields.length === 3 ? 'three' : 'five'} final dimensions against the real Room.</label>
    </fieldset>
  </section>;
}
