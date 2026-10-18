import { useEffect, useRef, useState } from 'react';
import type { CaptureDraft, CaptureView, ReferenceRequest, ReferenceResult } from '@/shared/api/types';
import { capturePhotoUrl, captureRequest } from '@/shared/api/client';
type Point=readonly[number,number];
export function ReferenceCalibration({capture,draft,edit,disabled}:{capture:CaptureView;draft:CaptureDraft;edit:(value:CaptureDraft)=>void;disabled:boolean}) {
  const [photoId,setPhotoId]=useState(''),[url,setUrl]=useState(''),[points,setPoints]=useState<ReadonlyArray<Point>>([]);
  const [plane,setPlane]=useState<'floor'|'wall'>('floor'),[field,setField]=useState<'widthM'|'depthM'|'heightM'|'notchWidthM'|'notchDepthM'>('widthM');
  const [type,setType]=useState<'a4'|'measured'>('a4'),[refWidth,setRefWidth]=useState(.210),[refHeight,setRefHeight]=useState(.297);
  const [ack,setAck]=useState(false),[result,setResult]=useState<ReferenceResult|null>(null),[message,setMessage]=useState(''),[busy,setBusy]=useState(false);
  const photo=capture.photos?.find(p=>p.id===photoId && p.state==='accepted');
  const latestDraft=useRef(draft);latestDraft.current=draft;
  const calculation=useRef<AbortController|null>(null);
  useEffect(()=>{
    calculation.current?.abort();setPoints([]);setAck(false);setResult(null);setUrl('');setBusy(false);
    if(!photo)return;
    const abort=new AbortController();let objectUrl='';
    capturePhotoUrl(capture.id,photo.id,abort.signal).then(value=>{objectUrl=value;if(!abort.signal.aborted)setUrl(value);else URL.revokeObjectURL(value);})
      .catch(()=>{if(!abort.signal.aborted)setMessage('Canonical photo is unavailable. Use typed dimensions.');});
    return()=>{abort.abort();calculation.current?.abort();if(objectUrl)URL.revokeObjectURL(objectUrl);};
  },[capture.id,capture.revision,photo?.id,photo?.sha256,draft.topology]);
  const calculate=async()=>{
    if(!photo||!photo.sha256||points.length!==6)return;
    setBusy(true);setMessage('');
    calculation.current?.abort();const abort=new AbortController();calculation.current=abort;
    if(!['widthM','depthM','heightM',...(draft.topology==='L-shaped'?['notchWidthM','notchDepthM']:[])].includes(field)){setMessage('Choose an active Room dimension.');setBusy(false);return;}
    const request:ReferenceRequest={expectedRevision:capture.revision,photoId:photo.id,photoHash:photo.sha256,referenceType:type,
      referenceWidthM:refWidth,referenceHeightM:refHeight,plane,perspective1x:ack,coplanar:ack,visible:ack,dimensionsReviewed:ack,marksReviewed:ack,
      corners:points.slice(0,4) as unknown as ReferenceRequest['corners'],segments:[{field,start:points[4]!,end:points[5]!}]};
    try {const value=await captureRequest<ReferenceResult>(`/api/captures/${capture.id}/calibrate`,'POST',request,abort.signal);
      if(abort.signal.aborted)return;
      setResult(value);
      if(value.status==='provisional') {
        let next={...latestDraft.current,dimensionsConfirmed:false};
        const evidence=[...(latestDraft.current.dimensionEvidence??[])];
        for(const estimate of value.estimates??[]) {
          // Existing typed values are preserved; user can deliberately replace them in the numeric step.
          if(next[estimate.field]==null)next={...next,[estimate.field]:estimate.valueM};
          evidence.push({field:estimate.field,valueM:estimate.valueM,photoId:photo.id,photoHash:photo.sha256,overrideReason:''});
        }
        edit({...next,dimensionEvidence:evidence});
      }
    } catch(error){if(!abort.signal.aborted)setMessage(error instanceof Error?error.message:'Reference calculation unavailable. Use typed dimensions.');}
    finally{if(!abort.signal.aborted)setBusy(false);}
  };
  return <details className="reference-calibration"><summary>Optional known-size reference prefill</summary>
    <p>Use a flat A4 sheet or measured rigid rectangle in the same plane as the visible endpoints. Use a standard 1× perspective photo. A floor reference cannot measure ceiling height. Ordinary door or furniture bounding boxes do not establish metres.</p>
    <fieldset disabled={disabled||busy}><legend>User-marked coplanar calibration</legend>
      <label>Canonical photo<select aria-label="Canonical photo" value={photoId} onChange={e=>setPhotoId(e.target.value)}><option value="">Choose an accepted photo</option>{capture.photos?.filter(p=>p.state==='accepted').map((p,i)=><option value={p.id} key={p.id}>Photo {i+1}</option>)}</select></label>
      <label>Reference<select aria-label="Reference" value={type} onChange={e=>{setType(e.target.value as typeof type);setAck(false);if(e.target.value==='a4'){setRefWidth(.210);setRefHeight(.297);}}}><option value="a4">Flat A4: 210 × 297 mm</option><option value="measured">Measured rigid rectangle</option></select></label>
      <div className="dimension-grid"><label>Reference width (m)<input type="number" value={refWidth} step=".001" readOnly={type==='a4'} onChange={e=>{setRefWidth(Number(e.target.value));setAck(false);}}/></label>
        <label>Reference height (m)<input type="number" value={refHeight} step=".001" readOnly={type==='a4'} onChange={e=>{setRefHeight(Number(e.target.value));setAck(false);}}/></label></div>
      <label>Physical plane<select value={plane} onChange={e=>{const next=e.target.value as typeof plane;setPlane(next);setField(next==='wall'?'heightM':'widthM');setAck(false);}}><option value="floor">Flat floor plane</option><option value="wall">Flush wall plane</option></select></label>
      <label>Complete dimension segment<select value={field} onChange={e=>setField(e.target.value as typeof field)}>
        {plane==='floor'?<><option value="widthM">Width: full floor-wall edge</option><option value="depthM">Depth: full floor-wall edge</option>{draft.topology==='L-shaped'?<><option value="notchWidthM">Notch width: full horizontal notch edge</option><option value="notchDepthM">Notch depth: full vertical notch edge</option></>:null}</>:<option value="heightM">Height: floor to ceiling</option>}</select></label>
      {url&&photo?<><p>Mark corners 1–4 around the known rectangle, starting at the width edge; then the two actual dimension endpoints. Coordinates use the canonical oriented image.</p>
        <button type="button" onClick={()=>{setPoints([]);setAck(false);}}>Clear marks</button>
        <div className="calibration-image"><img src={url} alt="Private canonical photo for user-authored calibration"
          onClick={e=>{if(points.length>=6)return;const bounds=e.currentTarget.getBoundingClientRect();setPoints([...points,[(e.clientX-bounds.left)/bounds.width*(photo.widthPx??0),(e.clientY-bounds.top)/bounds.height*(photo.heightPx??0)]]);setAck(false);}}/>
          <svg viewBox={`0 0 ${photo.widthPx} ${photo.heightPx}`} aria-hidden="true">{points.map(([x,y],i)=><g key={i}><circle cx={x} cy={y} r="8" fill="#ff7b55"/><text x={x+12} y={y} fill="white" fontSize="22">{i+1}</text></g>)}</svg></div>
        <div className="mark-coordinates">{Array.from({length:6},(_,i)=><div key={i}><strong>{i<4?`Corner ${i+1}`:`Endpoint ${i-3}`}</strong>{[0,1].map(axis=><label key={axis}>{axis?'y':'x'} (px)<input aria-label={`Mark ${i+1} ${axis?'y':'x'}`} type="number" value={points[i]?.[axis]??''} onChange={e=>{
          const next=Array.from({length:6},(_,j)=>points[j]??[0,0]) as Point[];const point=[...next[i]!] as [number,number];point[axis]=Number(e.target.value);next[i]=point;setPoints(next);setAck(false);
        }}/></label>)}</div>)}</div>
      </>:null}
      <label className="check"><input type="checkbox" checked={ack} onChange={e=>setAck(e.target.checked)}/>I confirm known size, ordered marks, full visible endpoints, the same flat physical plane and standard 1× projection.</label>
      <button type="button" disabled={!photo||points.length!==6||!ack||busy} onClick={calculate}>{busy?'Calculating…':'Calculate provisional estimate'}</button>
    </fieldset>
    {result?<p role="status" className="capture-warning">{result.status==='provisional'?'Provisional, editable estimate. Mandatory final dimension confirmation remains. Sensitivity is not metric confidence.':`Typed input required: ${result.reason}. No dimensions were invented.`}</p>:null}
    {message?<p role="alert">{message}</p>:null}
  </details>;
}
