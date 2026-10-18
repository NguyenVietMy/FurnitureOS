import { useCallback, useEffect, useRef, useState } from 'react';
import type { CaptureConfig, CaptureDeletionStatus, CaptureDraft, CaptureGenerationResult, CaptureIssue, CaptureView } from '@/shared/api/types';
import { CaptureApiError, captureRequest, setCaptureAuthorization } from '@/shared/api/client';
import { dimensionFields } from './capture-topology';
import { captureAuth, ensureAnonymous, isAnonymousSession, requireAnonymousSession } from '@/shared/auth/supabase';
const blank: CaptureDraft = { roomType: '', topology: '', widthM: null, depthM: null, heightM: null,
  dimensionsConfirmed: false, wallReviews: [], openings: [], furnitureAcknowledged: false, dimensionEvidence: [] };
export function useCapture() {
  const [config,setConfig] = useState<CaptureConfig | null>(null);
  const [capture,setCapture] = useState<CaptureView | null>(null);
  const [draft,setDraftState] = useState<CaptureDraft>(blank);
  const [issues,setIssues] = useState<ReadonlyArray<CaptureIssue>>([]);
  const [generation,setGeneration] = useState<CaptureGenerationResult | null>(null);
  const [receivedAtMs,setReceivedAtMs] = useState<number|undefined>(undefined);
  const [message,setMessage] = useState('');
  const [pending,setPending] = useState(false);
  const [dirty,setDirty] = useState(false);
  const sequence = useRef(0), owner = useRef<string | null>(null), active = useRef<AbortController | null>(null);
  useEffect(() => {
    const abort = new AbortController();
    fetch('/api/captures/config',{signal:abort.signal}).then(response => response.json()).then(setConfig).catch(() => {
      if (!abort.signal.aborted) setMessage('Capture configuration is unavailable.');
    });
    return () => { abort.abort(); active.current?.abort(); sequence.current++; };
  },[]);
  useEffect(() => {
    if (!config?.storageReady) return;
    const auth = captureAuth(config);
    setCaptureAuthorization(async () => {
      const {data,error} = await auth.getSession();
      if (error || !data.session) throw new Error('Anonymous account access was lost. Create a new Capture to continue.');
      return requireAnonymousSession(data.session).access_token;
    });
    const {data} = auth.onAuthStateChange((_event,session) => {
      const next = isAnonymousSession(session)?session.user.id:null;
      if (owner.current !== next) {
        owner.current = next; sequence.current++; active.current?.abort();
        setCapture(null); setDraftState(blank); setGeneration(null); setIssues([]); setPending(false);
        if (!next) setMessage('Anonymous account access was lost. Your private preview was cleared.');
        else {
          const saved=localStorage.getItem(`furnitureos.capture.${next}`);
          const restoration=sequence.current;
          if(saved) queueMicrotask(()=>captureRequest<CaptureView>(`/api/captures/${saved}`,'GET').then(restored=>{
            if(owner.current===next&&sequence.current===restoration) {setCapture(restored);setDraftState(restored.draft);setDirty(false);}
          }).catch(()=>{if(owner.current===next&&sequence.current===restoration)localStorage.removeItem(`furnitureos.capture.${next}`);}));
        }
      }
      if(session&&!isAnonymousSession(session))setMessage('Capture requires an anonymous account. Your existing account has not been changed.');
    });
    return () => { data.subscription.unsubscribe(); setCaptureAuthorization(null); owner.current=null; };
  },[config]);
  useEffect(()=>{
    if(!capture||capture.state==='deleting')return;
    const timer=setTimeout(()=>{sequence.current++;active.current?.abort();setCapture(null);setDraftState(blank);setGeneration(null);setIssues([]);setMessage('Capture expired. Private access and previews were cleared.');if(owner.current)localStorage.removeItem(`furnitureos.capture.${owner.current}`);},Math.max(0,Date.parse(capture.expiresAt)-Date.now()));
    return()=>clearTimeout(timer);
  },[capture?.id,capture?.expiresAt]);
  const install = (next: CaptureView) => { setCapture(next); setDraftState(next.draft); setDirty(false); if(owner.current) localStorage.setItem(`furnitureos.capture.${owner.current}`,next.id); };
  const roomDetailsUnsaved = Boolean(capture && (capture.draft.topology !== draft.topology
    || dimensionFields(draft.topology).some(field => (capture.draft[field] ?? null) !== (draft[field] ?? null))));
  const edit = (next: CaptureDraft) => {
    if (next.topology !== draft.topology) {
      const cleared = {...next};
      for (const evidence of draft.dimensionEvidence ?? []) {
        if (!evidence.overrideReason?.trim() && draft[evidence.field] === evidence.valueM && cleared[evidence.field] === evidence.valueM) cleared[evidence.field] = null;
      }
      next = {...cleared, dimensionsConfirmed:false, wallReviews:[], dimensionEvidence:[],
        openings:(next.openings ?? []).map(opening=>({...opening,wallId:null,reviewed:false}))};
    }
    sequence.current++; active.current?.abort(); setPending(false); setGeneration(null); setIssues([]);
    setDraftState(next); setDirty(true);
  };
  const execute = async <T,>(work:(signal:AbortSignal)=>Promise<T>, accept:(result:T)=>void) => {
    active.current?.abort(); const abort = new AbortController(); active.current=abort;
    const ticket=++sequence.current, account=owner.current;
    setPending(true); setMessage(''); setIssues([]); setGeneration(null);
    try {
      const result = await work(abort.signal);
      if (!abort.signal.aborted && ticket===sequence.current && account===owner.current) accept(result);
    } catch (error) {
      if (!abort.signal.aborted && ticket===sequence.current) setMessage(error instanceof Error ? error.message : 'This request could not complete.');
    } finally { if (ticket===sequence.current) setPending(false); }
  };
  const create = async () => {
    if (!config) return;
    try { const session=await ensureAnonymous(config); owner.current=session.user.id; }
    catch(error) { setMessage(error instanceof Error?error.message:'Anonymous sign-in failed.'); return; }
    await execute(signal=>captureRequest<CaptureView>('/api/captures','POST',{consent:true},signal),install);
  };
  const savePendingDraft = async (current:CaptureView,signal:AbortSignal) => {
    if(!dirty)return current;
    const saved=await captureRequest<CaptureView>(`/api/captures/${current.id}/draft`,'PATCH',{expectedRevision:current.revision,draft},signal);
    if(signal.aborted)throw new DOMException('Aborted','AbortError');
    install(saved);return saved;
  };
  const upload = async (file:File,wall:string) => {
    if (!capture) return;
    if (!['image/jpeg','image/png'].includes(file.type) || file.size>4_000_000) {
      setMessage('Choose a JPEG or PNG photo no larger than 4 MB. Export HEIC photos to a supported format.'); return;
    }
    const before=capture;
    await execute(async signal => {
      const current=await savePendingDraft(before,signal);
      const reserved=await captureRequest<CaptureView>(`/api/captures/${current.id}/photos`,'POST',
        {expectedRevision:current.revision,declaredBytes:file.size,primaryWallId:wall},signal);
      if(signal.aborted)throw new DOMException("Aborted","AbortError");
      install(reserved);
      const oldIds=new Set(current.photos?.map(photo=>photo.id));
      const photo=reserved.photos?.find(item=>!oldIds.has(item.id));
      if (!photo) throw new Error('Photo reservation was incomplete.');
      return captureRequest<CaptureView>(`/api/captures/${current.id}/photos/${photo.id}/content?expectedRevision=${reserved.revision}`,'POST',file,signal);
    },install);
  };
  const photoAction = async (id:string, action:'analyze'|'remove'|'associate', wall?:string, observed?:ReadonlyArray<string>) => {
    if (!capture) return;
    const before=capture;
    await execute(async signal=>{
      const current=await savePendingDraft(before,signal);
      return captureRequest<CaptureView>(`/api/captures/${current.id}/photos/${id}${action==='analyze'?'/analyze':''}`,
        action==='analyze'?'POST':action==='remove'?'DELETE':'PATCH',
        {expectedRevision:current.revision,...(action==='associate'?{primaryWallId:wall,observedWallIds:observed??[]}: {})},signal);
    },install);
  };
  const save = async () => {
    if (!capture) return;
    const current=capture;
    await execute(signal=>captureRequest<CaptureView>(`/api/captures/${current.id}/draft`,'PATCH',
      {expectedRevision:current.revision,draft},signal),saved=>{
        install(saved);setMessage('Room details saved. Review the Opening inventory and explicitly confirm the saved dimensions.');
      });
  };
  const confirm = async () => {
    if(roomDetailsUnsaved){setMessage('Save Room details before confirming measurements and reviewing the Opening inventory.');return;}
    if (!capture) return;
    const current=capture;
    await execute(async signal => {
      const saved=await captureRequest<CaptureView>(`/api/captures/${current.id}/draft`,'PATCH',{expectedRevision:current.revision,draft},signal);
      return captureRequest<{capture:CaptureView;issues?:ReadonlyArray<CaptureIssue>;status:string}>(`/api/captures/${current.id}/confirm`,'POST',
        {expectedRevision:saved.revision},signal);
    },result=>{install(result.capture);setIssues(result.issues??[]);setMessage(result.status==='confirmed'?'Room confirmed. Choose a Style image to generate.':'Review the highlighted required details.');});
  };
  const generate = async (referenceId:string) => {
    if (!capture || dirty) { setMessage('Confirm your edited Room before generation.'); return; }
    const current=capture;
    await execute(signal=>captureRequest<CaptureGenerationResult>(`/api/captures/${current.id}/generate`,'POST',
      {expectedRevision:current.revision,referenceId},signal),result=>{setReceivedAtMs(performance.now());setGeneration(result);});
  };
  const remove = async () => {
    if (!capture) return;
    const current=capture;
    await execute(signal=>captureRequest<CaptureView>(`/api/captures/${current.id}`,'DELETE',{expectedRevision:current.revision},signal),
      next=>{install(next);setMessage('Capture inaccessible. Physical deletion is pending and will retry if needed.');});
  };
  const reload = async () => {
    if (!capture) return;
    const current=capture;
    await execute(signal=>(current.state==='deleting'
      ? captureRequest<CaptureDeletionStatus>(`/api/captures/${current.id}/deletion`,'GET',undefined,signal).then(status=>({...current,cleanupStatus:status.cleanupStatus}))
      : captureRequest<CaptureView>(`/api/captures/${current.id}`,'GET',undefined,signal)).catch(error=>{
      if(current.state==='deleting'&&error instanceof CaptureApiError&&error.status===404)return null;
      throw error;
    }),next=>{if(next)install(next);else{setCapture(null);setDraftState(blank);if(owner.current)localStorage.removeItem(`furnitureos.capture.${owner.current}`);setMessage('Capture deletion completed.');}});
  };
  const installDesign = useCallback((design: import('@/shared/api/types').SolvedDesign) => {
    setGeneration(current => current?.status==='generated' && current.result.status==='solved'
      && current.result.design.swap?.status==='available' && design.swap?.status==='available'
      && current.result.design.swap.sessionId===design.swap.sessionId && design.swap.version>=current.result.design.swap.version
      ? {...current,result:{...current.result,design}} : current);
  },[]);
  return {config,capture,draft,edit,save,roomDetailsUnsaved,issues,generation,receivedAtMs,message,pending,dirty,create,upload,photoAction,confirm,generate,remove,reload,installDesign};
}
