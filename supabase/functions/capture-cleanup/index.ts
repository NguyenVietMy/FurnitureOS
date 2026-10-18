/** Durable Storage removal; this source is inactive until reviewed activation. */
declare const Deno: { env: { get(name: string): string | undefined }; serve(handler: (request: Request) => Promise<Response>): void };
type Job = { id: string; lease_token: string; capture_id: string | null; keys: string[]; removed: string[]; reason: string };
type Env = { url: string; secretKey: string; current: string; publicKey?: string; previous?: string; previousUntil?: string };
type Requester = typeof fetch;

async function equalSecret(a: string, b: string): Promise<boolean> {
  if (!/^[a-f0-9]{64}$/.test(b) || a.length > 256) return false;
  const [x,y] = await Promise.all([a,b].map(value => crypto.subtle.digest('SHA-256',new TextEncoder().encode(value))));
  const p=new Uint8Array(x!),q=new Uint8Array(y!); let difference=0;
  for(let i=0;i<32;i++) difference|=p[i]!^q[i]!;
  return difference===0;
}

export async function cleanupHandler(request: Request, env: Env, requester: Requester = fetch): Promise<Response> {
  const presented=request.headers.get('x-capture-cleanup-secret') ?? '';
  const current=await equalSecret(presented,env.current);
  const previous=env.previous && env.previousUntil && Date.parse(env.previousUntil)>Date.now()
    && await equalSecret(presented,env.previous);
  if(request.method!=='POST' || (!current && !previous)) return new Response('Denied',{status:401});
  if(!current && previous) {
    if(!env.publicKey)return new Response('Denied',{status:401});
    try {
      const status=await requester(env.url+'/rest/v1/rpc/capture_cleanup_rotation_status',{method:'POST',
        headers:{apikey:env.publicKey,'Content-Type':'application/json'},body:'{}',signal:AbortSignal.timeout(5000)});
      if(!status.ok || await status.json()!==false)return new Response('Denied',{status:401});
    } catch { return new Response('Denied',{status:401}); }
  }
  const deadline=Date.now()+60000;
  const headers={apikey:env.secretKey,Authorization:`Bearer ${env.secretKey}`,'Content-Type':'application/json'};
  async function call(path: string, method: string, body?: unknown) {
    if(Date.now()>=deadline) throw new Error('deadline');
    const response=await requester(env.url+path,{method,headers,body:body===undefined?undefined:JSON.stringify(body),
      signal:AbortSignal.timeout(Math.max(1,Math.min(5000,deadline-Date.now())))});
    if(!response.ok) throw new Error('service-unavailable');
    const reader=response.body?.getReader(),chunks:Uint8Array[]=[];let length=0;
    if(reader)while(true){const part=await reader.read();if(part.done)break;length+=part.value.byteLength;
      if(length>262144){await reader.cancel();throw new Error('response-limit');}chunks.push(part.value);}
    const bytes=new Uint8Array(length);let offset=0;for(const chunk of chunks){bytes.set(chunk,offset);offset+=chunk.length;}
    const text=new TextDecoder().decode(bytes);
    return text ? JSON.parse(text) : {};
  }
  const rpc=(action:string,payload:unknown={})=>call('/rest/v1/rpc/capture_cleanup','POST',{p_action:action,p_payload:payload});
  let completed=0;
  try {
    const jobs: Job[]=await rpc('claim');
    for(const job of jobs.slice(0,10)) {
      if(Date.now()>deadline-5000) { await rpc('yield',{id:job.id,lease:job.lease_token}); continue; }
      if(job.reason==='unrecognized-path') { await rpc('fail',{id:job.id,lease:job.lease_token}); continue; }
      try {
        for(const key of job.keys) {
          if(job.removed.includes(key)) continue;
          const uuid='[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}';
          if(!new RegExp(`^${uuid}/${uuid}/${uuid}\\.jpg$`).test(key)) throw new Error('unsupported-key');
          try { await call('/storage/v1/object/captures','DELETE',{prefixes:[key]}); } catch { /* An exact absence check can resolve an ambiguous/previous removal. */ }
          const slash=key.lastIndexOf('/'),prefix=key.slice(0,slash),name=key.slice(slash+1);
          const listing: Array<{name:string}>=await call('/storage/v1/object/list/captures','POST',
            {prefix,search:name,limit:100,offset:0,sortBy:{column:'name',order:'asc'}});
          if(!Array.isArray(listing) || listing.some(item=>item.name===name)) throw new Error('removal-unconfirmed');
          await rpc('progress',{id:job.id,lease:job.lease_token,key});
        }
        await rpc('finish',{id:job.id,lease:job.lease_token}); completed++;
      } catch {
        await rpc('fail',{id:job.id,lease:job.lease_token});
      }
    }
    if(Date.now()<deadline-5000) {
      const page=await rpc('audit-page');
      await rpc('audit',{objects:page.objects,cursor:page.cursor});
    }
    if(request.headers.get('x-capture-cleanup-scheduled')==='1') await rpc('scheduled');
    return Response.json({status:'complete',completed,scheduled:request.headers.get('x-capture-cleanup-scheduled')==='1'});
  } catch { return Response.json({status:'pending',completed},{status:503}); }
}

if(typeof Deno!=='undefined') Deno.serve(request=>cleanupHandler(request,{
  url:Deno.env.get('SUPABASE_URL') ?? '',secretKey:Deno.env.get('SUPABASE_SERVICE_ROLE_KEY') ?? Deno.env.get('SUPABASE_SECRET_KEY') ?? '',
  current:Deno.env.get('CAPTURE_CLEANUP_SECRET') ?? '',previous:Deno.env.get('CAPTURE_CLEANUP_PREVIOUS_SECRET'),
  publicKey:Deno.env.get('SUPABASE_PUBLISHABLE_KEY') ?? Deno.env.get('SUPABASE_ANON_KEY'),
  previousUntil:Deno.env.get('CAPTURE_CLEANUP_PREVIOUS_UNTIL')
}));
