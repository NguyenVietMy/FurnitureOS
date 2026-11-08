import {useEffect,useState} from 'react';
import {createRoot} from 'react-dom/client';
import {MeshPreview} from './MeshPreview';
import './style.css';
import './expansion.css';

type Candidate = {productId:string; previewUrl:string|null; dimensions?:number[]; proposal:{displayName:string;proposedCategory:string;sourceSha256:string}; decision:unknown};
type Review = {batchId:string;intakeSha256:string;revision:number;evidenceKind:string;reviewerIdentity:string;candidates:Candidate[];references:{sha256:string;images:{id:string;sha256:string;fileName:string;privateStyleId:string}[]}};
function Workbench() {
  const [data,setData] = useState<Review|null>(null), [error,setError] = useState(''), [selected,setSelected] = useState(0);
  useEffect(()=> { const c = new AbortController(); fetch('/api/expansion',{signal:c.signal}).then(async(r)=>{if(!r.ok) throw new Error(await r.text()); return r.json() as Promise<Review>;}).then(setData).catch((e:unknown)=>{if(!c.signal.aborted) setError(String(e));}); return ()=>c.abort(); },[]);
  if(error) return <main><h1>Review unavailable</h1><p role="alert">{error}</p></main>;
  if(!data) return <main>Loading bounded Mesh batch…</main>;
  const c = data.candidates[selected]!;
  return <main>
    <h1>Expansion Mesh review · {data.batchId}</h1>
    <p>{data.reviewerIdentity} · {data.evidenceKind} · revision {data.revision}</p>
    <p>Intake SHA256: {data.intakeSha256}</p>
    <label>Candidate <select value={selected} onChange={(e)=>setSelected(Number(e.target.value))}>{data.candidates.map((p,i)=><option key={p.productId} value={i}>{i+1}. {p.productId}{p.previewUrl?'':' · unprepared'}</option>)}</select></label>
    <h2>{c.proposal.displayName}</h2><p>Proposed category: {c.proposal.proposedCategory}. Metadata proposes a role; it does not establish suitability or Style.</p>
    <p>Measured width × height × depth: {c.dimensions?.map((n)=>n.toFixed(3)).join(' × ') ?? 'unprepared'} metres. Source: {c.proposal.sourceSha256}</p>
    {c.previewUrl ? <MeshPreview key={c.productId} url={c.previewUrl}/> : <p role="status">No acknowledged Mesh. Prepare this candidate before visual review.</p>}
    <h2>Frozen Style references</h2><p>Review front, side, back, materials, +Z front and metre dimensions. Record suitability, Style and functional access decisions with actual view evidence. A drawn Mesh is technical evidence; acceptance requires the named reviewer's explicit decisions.</p>
    <div className="references">{data.references.images.map((r)=><figure key={r.id}><img src={`/references/${r.sha256}/${r.fileName}`} alt={`Frozen ${r.id}, private ${r.privateStyleId}`}/><figcaption>{r.id} · {r.privateStyleId}</figcaption></figure>)}</div>
    <p>Use browser screenshots with the CLI observe command. Stop this read-only server before importing observations or decisions. No decision is made by this page.</p>
  </main>;
}
createRoot(document.getElementById('root')!).render(<Workbench/>);
