import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { Session } from '@supabase/supabase-js';
import type { CaptureConfig } from '../src/shared/api/types';
const auth=vi.hoisted(()=>({getSession:vi.fn(),signInAnonymously:vi.fn(),signOut:vi.fn(),updateUser:vi.fn()}));
vi.mock('@supabase/supabase-js',()=>({createClient:()=>({auth})}));
import { ensureAnonymous, isAnonymousSession, requireAnonymousSession } from '../src/shared/auth/supabase';
const config={storageReady:true,authUrl:'https://controlled.invalid',publishableKey:'public'} as CaptureConfig;
function session(flag:boolean|undefined) {
  return {access_token:'controlled',user:{id:'same-owner',...(flag===undefined?{}:{is_anonymous:flag}),user_metadata:{is_anonymous:true}}} as unknown as Session;
}
beforeEach(()=>{vi.clearAllMocks();});
describe('anonymous-only SDK boundary; no permanent account mutation',()=>{
  for(const flag of [false,undefined,true]) {
    it(`restored flag ${String(flag)} requires exact anonymous identity`,async()=>{
      const profile=session(flag);auth.getSession.mockResolvedValue({data:{session:profile},error:null});
      if(flag===true)expect(await ensureAnonymous(config)).toBe(profile);
      else await expect(ensureAnonymous(config)).rejects.toThrow('requires an anonymous account');
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
