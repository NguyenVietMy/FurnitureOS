import { useEffect, useState } from 'react';
import { fetchLiveBedroomConfig } from '@/shared/api/client';
import type { CaptureGenerationResult, LiveBedroomConfig } from '@/shared/api/types';
export function CaptureGeneration({result,available,confirmed,pending,generate,review}:{result:CaptureGenerationResult|null;available:boolean;confirmed:boolean;pending:boolean;generate:(id:string)=>void;review:()=>void}) {
  const [config,setConfig]=useState<LiveBedroomConfig|null>(null),[reference,setReference]=useState('');
  useEffect(()=>{const abort=new AbortController();fetchLiveBedroomConfig(abort.signal).then(setConfig).catch(()=>{});return()=>abort.abort();},[]);
  const failed=result?.status==='generated'&&result.result.status==='failed'?result.result:null;
  return <section><h2>Generate the confirmed Room</h2><p>The current generator selects one real bed and optionally one rug. FurnitureOS checks fit and connected walking space.</p>
    <fieldset disabled={pending}><legend>Style inspiration</legend><div className="capture-reference-grid">{config?.references.map(item=><label key={item.id}>
      <input type="radio" name="capture-reference" checked={reference===item.id} onChange={()=>setReference(item.id)}/>
      <img src={item.imageUrl} alt={item.label}/><span>{item.label}</span></label>)}</div></fieldset>
    <button disabled={!available||!confirmed||!reference||pending} onClick={()=>generate(reference)}>{pending?'Checking the Design…':'Generate confirmed Room'}</button>
    {!available?<p className="capture-warning">Live generation is unavailable in this runtime.</p>:null}
    {!confirmed?<p>Complete review and confirm this Room first.</p>:null}
    {result?.status==='blocked'?<div role="alert"><strong>Room details need review.</strong><p>{result.detail}</p>{result.issues?.map((issue,i)=><p key={i}>{issue.detail}</p>)}</div>:null}
    {failed?<div className="capture-result" role="alert"><strong>{failed.code==='no-valid-design'
      ? failed.designFailure?.search.exhaustive?'No valid Design fits these supported requests.':'No valid Design found within the supported search.'
      :'Generation could not complete.'}</strong><p>{failed.detail}</p>
      <button onClick={review}>Review dimensions and Openings</button><button disabled={pending||!available} onClick={()=>generate(reference)}>Retry generation explicitly</button></div>:null}
  </section>;
}
