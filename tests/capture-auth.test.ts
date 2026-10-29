import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { Session } from '@supabase/supabase-js';
import type { CaptureConfig } from '../src/shared/api/types';
const auth=vi.hoisted(()=>({onAuthStateChange:vi.fn(()=>({data:{subscription:{unsubscribe:vi.fn()}}})),getSession:vi.fn(),getUser:vi.fn(),signInAnonymously:vi.fn(),signOut:vi.fn(),updateUser:vi.fn(),verifyOtp:vi.fn(),refreshSession:vi.fn(),signInWithOtp:vi.fn()}));
vi.mock('@supabase/supabase-js',()=>({createClient:()=>({auth})}));
import { ensureAnonymous, isAnonymousSession, requireAnonymousSession, beginEmailLink, finishEmailLink, beginReturningSignIn } from '../src/shared/auth/supabase';
const config={storageReady:true,authUrl:'https://controlled.invalid',publishableKey:'public'} as CaptureConfig;
function session(flag:boolean|undefined) {
  return {access_token:'controlled',user:{id:'same-owner',...(flag===undefined?{}:{is_anonymous:flag}),user_metadata:{is_anonymous:true}}} as unknown as Session;
}
beforeEach(()=>{vi.clearAllMocks();});
describe('current owner SDK boundary; no implicit account replacement',()=>{
  for(const flag of [false,undefined,true]) {
    it(`restored flag ${String(flag)} requires a current explicit owner identity`,async()=>{
      const profile=session(flag);auth.getSession.mockResolvedValue({data:{session:profile},error:null});
      if(flag!==undefined)expect(await ensureAnonymous(config)).toBe(profile);
      else await expect(ensureAnonymous(config)).rejects.toThrow('Refresh');
      expect(auth.signInAnonymously).not.toHaveBeenCalled();expect(auth.signOut).not.toHaveBeenCalled();expect(auth.updateUser).not.toHaveBeenCalled();
    });
    it(`new profile flag ${String(flag)} cannot substitute metadata`,async()=>{
      auth.getSession.mockResolvedValue({data:{session:null},error:null});const profile=session(flag);
      auth.signInAnonymously.mockResolvedValue({data:{session:profile},error:null});
      if(flag===true)expect(await ensureAnonymous(config)).toBe(profile);
      else await expect(ensureAnonymous(config)).rejects.toThrow('requires an anonymous account');
      expect(auth.signInAnonymously).toHaveBeenCalledOnce();expect(auth.signOut).not.toHaveBeenCalled();expect(auth.updateUser).not.toHaveBeenCalled();
      expect(isAnonymousSession(profile)).toBe(flag===true);
      if(flag!==true)expect(()=>requireAnonymousSession(profile)).toThrow('requires an anonymous account');
    });
  }
});

it('verified linking refreshes credentials and preserves the UUID',async()=>{
  const before=session(true),after=session(false);
  auth.getSession.mockResolvedValue({data:{session:before},error:null});
  auth.updateUser.mockResolvedValue({data:{user:before.user},error:null});
  await beginEmailLink(config,'person@example.test','same-owner');
  expect(auth.updateUser).toHaveBeenCalledWith({email:'person@example.test'});
  auth.verifyOtp.mockResolvedValue({data:{session:after},error:null});
  auth.refreshSession.mockResolvedValue({data:{session:after},error:null});
  auth.getUser.mockResolvedValue({data:{user:after.user},error:null});
  expect(await finishEmailLink(config,'person@example.test','123456','same-owner')).toBe(after);
  expect(auth.verifyOtp).toHaveBeenCalledWith({email:'person@example.test',token:'123456',type:'email_change'});
  expect(auth.refreshSession).toHaveBeenCalledOnce();
  expect(auth.signOut).not.toHaveBeenCalled();
});

it('existing-account conflict preserves the anonymous owner and returning sign-in requires a deliberate switch',async()=>{
  auth.getSession.mockResolvedValue({data:{session:session(true)},error:null});
  auth.updateUser.mockResolvedValue({data:{user:null},error:{code:'email_exists'}});
  await expect(beginEmailLink(config,'taken@example.test','same-owner')).rejects.toThrow('already');
  expect(auth.signOut).not.toHaveBeenCalled();
  await expect(beginReturningSignIn(config,'person@example.test',false)).rejects.toThrow('switch');
  await beginReturningSignIn(config,'person@example.test',true);
  expect(auth.signInWithOtp).toHaveBeenCalledWith({email:'person@example.test',options:{shouldCreateUser:false}});
});

it('a different current owner cannot finish an earlier email-link operation',async()=>{
  const changed={...session(true),user:{...session(true).user,id:'different-owner'}};
  auth.getSession.mockResolvedValue({data:{session:changed},error:null});
  await expect(finishEmailLink(config,'person@example.test','123456','same-owner')).rejects.toThrow('account changed');
  expect(auth.verifyOtp).not.toHaveBeenCalled();
  expect(auth.signOut).not.toHaveBeenCalled();
});

for(const boundary of ['refreshed-session','current-user'])it(`email linking cannot succeed with a different UUID at ${boundary}`,async()=>{
  const before=session(true),after=session(false);
  const different={...after,user:{...after.user,id:'different-owner'}};
  auth.getSession.mockResolvedValue({data:{session:before},error:null});
  auth.verifyOtp.mockResolvedValue({data:{session:different},error:null});
  auth.refreshSession.mockResolvedValue({data:{session:boundary==='refreshed-session'?different:after},error:null});
  auth.getUser.mockResolvedValue({data:{user:boundary==='current-user'?different.user:after.user},error:null});
  await expect(finishEmailLink(config,'person@example.test','123456','same-owner')).rejects.toThrow('not verified');
  expect(auth.signOut).not.toHaveBeenCalled();
});
