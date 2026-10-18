import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router';
import { useCapture } from './useCapture';
import { CapturePhotos } from './CapturePhotos';
import { ShapeSelection } from './ShapeSelection';
import { OpeningEditor } from './OpeningEditor';
import { RoomDimensions } from './RoomDimensions';
import { ReferenceCalibration } from './ReferenceCalibration';
import { RoomReviewPreview } from './RoomReviewPreview';
import { CaptureGeneration } from './CaptureGeneration';
import { RoomStage } from '@/features/design/RoomStage';
import { SwapControls } from '@/features/design/SwapControls';
import { NudgeControls } from '@/features/design/NudgeControls';
import { useMutationLock } from '@/features/design/useMutationLock';
import { useNudge } from '@/features/design/useNudge';
import './capture.css';
export default function CapturePage() {
  const flow=useCapture(),[consent,setConsent]=useState(false);
  const reviewRef=useRef<HTMLElement>(null);
  const errorsRef=useRef<HTMLDivElement>(null);
  useEffect(()=>{if(flow.issues.length)errorsRef.current?.focus();},[flow.issues]);
  const success=flow.generation?.status==='generated'&&flow.generation.result.status==='solved'?flow.generation.result:null;
  const lock=useMutationLock(success?.design.swap?.status==='available'?success.design.swap.sessionId:null);
  const nudge=useNudge(success?.design??null,flow.installDesign,lock);
  const capture=flow.capture;
  const confirmed=Boolean(capture?.state==='confirmed'&&!flow.dirty);
  const proposals=capture?.photos?.flatMap(p=>p.semantics?.openings??[])??[];
  const warn=capture?.photos?.some(p=>!p.semantics||p.semantics.detectedFurniture!=='absent')??false;
  const review=()=>reviewRef.current?.scrollIntoView({behavior:'auto',block:'start'});
  return <main className="capture-page" data-testid="capture-page"><header><Link to="/design">← Room preview</Link><p className="capture-eyebrow">Your Room Capture</p>
    <h1>Capture, correct, then confirm</h1><p>Stable labelled walls. Explicit measurements. A Design checked against the Room you confirm.</p></header>
    {!flow.config?<p role="status">Loading Capture availability…</p>:null}
    {flow.config&&!flow.config.storageReady?<section role="status" className="capture-warning"><h2>Capture is unavailable right now</h2><p>Private photo uploads are not available in this environment. You can <Link to="/design">explore Room preview</Link> and try Capture again later.</p></section>:null}
    {flow.message?<p role="status" className="capture-message">{flow.message}</p>:null}
    {flow.pending?<p role="status">Working on this request…</p>:null}
    {!capture&&flow.config?.storageReady?<section><h2>Private anonymous ownership first</h2>
      <p>Canonical photos and Room drafts expire 24 hours after creation. Delete at any time to revoke access immediately; physical removal follows scheduled cleanup and stays pending on failure. Clearing browser data can lose anonymous access.</p>
      <p>Explicit analysis sends the selected photo to Claude. Our deletion covers this service’s copies, not provider retention or copies already downloaded.</p>
      <label className="check"><input type="checkbox" checked={consent} onChange={e=>setConsent(e.target.checked)}/>I understand private photo handling, analysis submission and 24-hour retention.</label>
      <button disabled={!consent||flow.pending} onClick={flow.create}>Create private Capture</button></section>:null}
    {capture?.state==='deleting'?<section><h2>Deletion pending</h2><p>This Capture is inaccessible. Stored-byte removal retries until confirmed complete.</p><button onClick={flow.reload}>Check status</button></section>:capture?<>
      <div className="capture-lifecycle"><span>Expires: <time dateTime={capture.expiresAt}>{new Date(capture.expiresAt).toLocaleString()}</time></span>
        <button disabled={flow.pending} onClick={flow.reload}>Reload confirmed state</button><button disabled={flow.pending} onClick={flow.remove}>Delete Capture</button></div>
      <div className="capture-columns"><div className="capture-form">
        <ShapeSelection draft={flow.draft} edit={flow.edit} disabled={flow.pending}/>
        <CapturePhotos capture={capture} topology={flow.draft.topology} pending={flow.pending} analysisAvailable={flow.config?.analysisAvailable??false} upload={flow.upload} action={flow.photoAction}/>
        <section ref={reviewRef}><h2>Review all observed details</h2>
          {warn?<div className="capture-warning"><strong>Detected Furniture / unresolved detection</strong><p>This Design assumes an empty Room. Detected Furniture is not reconstructed or included.</p>
            <label className="check"><input type="checkbox" disabled={flow.pending} checked={flow.draft.furnitureAcknowledged??false} onChange={e=>flow.edit({...flow.draft,furnitureAcknowledged:e.target.checked})}/>I acknowledge the empty-Room assumption.</label></div>:null}
          <OpeningEditor draft={flow.draft} edit={flow.edit} disabled={flow.pending} proposals={proposals}/>
          <ReferenceCalibration capture={capture} draft={flow.draft} edit={flow.edit} disabled={flow.pending||flow.roomDetailsUnsaved}/>
          <RoomDimensions draft={flow.draft} edit={flow.edit} disabled={flow.pending} measurementsUnsaved={flow.roomDetailsUnsaved}/>
          <button disabled={flow.pending||!flow.dirty} onClick={flow.save}>Save Room details</button>
          {flow.issues.length?<div ref={errorsRef} className="capture-errors" role="alert" tabIndex={-1}><h3>Required details to resolve</h3><ul>{flow.issues.map((issue,i)=><li key={i}>{issue.detail}</li>)}</ul></div>:null}
          <button disabled={flow.pending||flow.roomDetailsUnsaved} onClick={flow.confirm}>Review and confirm Room</button>
        </section>
        <CaptureGeneration result={flow.generation} available={flow.config?.generationAvailable??false} confirmed={confirmed} pending={flow.pending} generate={flow.generate} review={review}/>
      </div><aside className="capture-preview"><RoomReviewPreview draft={flow.draft} confirmed={confirmed}/>
        {success?<><h2>Validated furnished Room</h2><RoomStage result={success.design} receivedAtMs={flow.receivedAtMs} generationId={success.generationId} nudge={nudge}/>
          <NudgeControls design={success.design} nudge={nudge} lock={lock}/><SwapControls design={success.design} onDesignChange={flow.installDesign} mutationLock={lock}/></>:null}
      </aside></div>
    </>:null}
  </main>;
}
