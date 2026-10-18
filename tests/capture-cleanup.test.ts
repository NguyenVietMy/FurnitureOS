import { describe, expect, it } from 'vitest';
import { cleanupHandler } from '../supabase/functions/capture-cleanup';
const current='a'.repeat(64);
const env={url:'https://controlled.invalid',secretKey:'test-service',current};
const key='11111111-1111-1111-1111-111111111111/22222222-2222-2222-2222-222222222222/33333333-3333-3333-3333-333333333333.jpg';
describe('controlled cleanup transport (not live scheduled deletion)',()=>{
  it('denies arbitrary public requests before privileged I/O',async()=>{
    let calls=0;
    const response=await cleanupHandler(new Request('https://worker.invalid',{method:'POST'}),env,async()=>{calls++;return Response.json({});});
    expect(response.status).toBe(401);expect(calls).toBe(0);
  });
  it('persists removal only after Storage confirms absence, then purges metadata',async()=>{
    const actions:string[]=[];
    const requester:typeof fetch=async(input,init)=>{
      const url=String(input),body=JSON.parse(String(init?.body??'{}'));
      if(url.endsWith('/capture_cleanup')) {
        actions.push(body.p_action);
        if(body.p_action==='claim')return Response.json([{id:'job',lease_token:'lease',keys:[key],removed:[],reason:'manual',capture_id:'capture'}]);
        if(body.p_action==='audit-page')return Response.json({objects:[],cursor:''});
        return Response.json({});
      }
      actions.push(init?.method==='DELETE'?'delete-bytes':'verify-absence');
      return Response.json(init?.method==='DELETE'?{}:[]);
    };
    const response=await cleanupHandler(new Request('https://worker.invalid',{method:'POST',headers:{'x-capture-cleanup-secret':current}}),env,requester);
    expect(response.status).toBe(200);
    expect(actions.indexOf('delete-bytes')).toBeLessThan(actions.indexOf('verify-absence'));
    expect(actions.indexOf('verify-absence')).toBeLessThan(actions.indexOf('progress'));
    expect(actions.indexOf('progress')).toBeLessThan(actions.indexOf('finish'));
  });
  it('keeps failure inventory and never purges when the file still exists',async()=>{
    const actions:string[]=[];
    const requester:typeof fetch=async(input,init)=>{
      const body=JSON.parse(String(init?.body??'{}'));
      if(String(input).endsWith('/capture_cleanup')) {
        actions.push(body.p_action);
        if(body.p_action==='claim')return Response.json([{id:'job',lease_token:'lease',keys:[key],removed:[],reason:'expiry'}]);
        if(body.p_action==='audit-page')return Response.json({objects:[],cursor:''});
        return Response.json({});
      }
      return Response.json(init?.method==='DELETE'?{}:[{name:key.split('/').at(-1)}]);
    };
    await cleanupHandler(new Request('https://worker.invalid',{method:'POST',headers:{'x-capture-cleanup-secret':current}}),env,requester);
    expect(actions).toContain('fail');expect(actions).not.toContain('finish');expect(actions).not.toContain('progress');
  });
  it('accepts previous secret only in persisted rotation window, revoked by scheduled success',async()=>{
    let revoked=false,privilegedCalls=0;
    const requester:typeof fetch=async(input,init)=>{
      if(String(input).endsWith('/capture_cleanup_rotation_status'))return Response.json(revoked);
      privilegedCalls++;const body=JSON.parse(String(init?.body??'{}'));
      if(body.p_action==='claim')return Response.json([]);
      if(body.p_action==='audit-page')return Response.json({objects:[],cursor:'saved-cursor'});
      if(body.p_action==='scheduled')revoked=true;
      return Response.json({});
    };
    const rotation={...env,publicKey:'public-test',previous:'b'.repeat(64),previousUntil:new Date(Date.now()+60000).toISOString()};
    const old=()=>new Request('https://worker.invalid',{method:'POST',headers:{'x-capture-cleanup-secret':rotation.previous}});
    expect((await cleanupHandler(old(),rotation,requester)).status).toBe(200);
    expect((await cleanupHandler(new Request('https://worker.invalid',{method:'POST',headers:{'x-capture-cleanup-secret':current,'x-capture-cleanup-scheduled':'1'}}),rotation,requester)).status).toBe(200);
    const before=privilegedCalls;expect((await cleanupHandler(old(),rotation,requester)).status).toBe(401);
    expect(privilegedCalls).toBe(before);
  });
  it('resumes removed inventory and retains unknown paths without byte operations',async()=>{
    const actions:string[]=[];
    const requester:typeof fetch=async(input,init)=>{
      expect(String(input)).toContain('/rest/v1/rpc/');const body=JSON.parse(String(init?.body??'{}'));actions.push(body.p_action);
      if(body.p_action==='claim')return Response.json([{id:'resumed',lease_token:'l',keys:[key],removed:[key],reason:'manual'},
        {id:'unknown',lease_token:'l2',keys:[],removed:[],reason:'unrecognized-path'}]);
      if(body.p_action==='audit-page')return Response.json({objects:[],cursor:'cursor-100'});
      if(body.p_action==='audit')expect(body.p_payload.cursor).toBe('cursor-100');
      return Response.json({});
    };
    await cleanupHandler(new Request('https://worker.invalid',{method:'POST',headers:{'x-capture-cleanup-secret':current}}),env,requester);
    expect(actions.filter(x=>x==='finish')).toHaveLength(1);expect(actions).toContain('fail');expect(actions).not.toContain('progress');
  });
});
