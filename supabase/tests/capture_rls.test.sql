-- Plain SQL contract proof, runnable without pgTAP in a disposable migrated database.
begin;
insert into auth.users(id,is_anonymous) values('11111111-1111-1111-1111-111111111111',true),('22222222-2222-2222-2222-222222222222',true);
select set_config('request.jwt.claims','{"is_anonymous":true}',true);
set local role authenticated;
select set_config('request.jwt.claim.sub','11111111-1111-1111-1111-111111111111',true);
do $$begin
 begin perform public.capture_user_operation('create'); raise exception 'missing consent accepted';
 exception when raise_exception then if sqlerrm<>'not-found' then raise; end if; end;
end $$;
select public.capture_user_operation('create',p_payload=>'{"consent":true}') as first_capture \gset
select (:'first_capture'::jsonb->>'id') as owned_capture \gset
do $$begin
 begin insert into public.captures(owner_id) values(auth.uid()); raise exception 'direct insert unexpectedly allowed';
 exception when insufficient_privilege then null; end;
 begin update public.captures set confirmed_revision=1; raise exception 'protected update unexpectedly allowed';
 exception when insufficient_privilege then null; end;
 begin delete from public.captures; raise exception 'direct deletion unexpectedly allowed';
 exception when insufficient_privilege then null; end;
 begin perform public.capture_authority('confirm',auth.uid(),gen_random_uuid(),1,gen_random_uuid(),'{}'); raise exception 'authority exposed';
 exception when insufficient_privilege then null; end;
end $$;
select public.capture_user_operation('lease',:'owned_capture',1,'{"kind":"session"}') as first_lease \gset
select (:'first_lease'::jsonb->>'lease') as owned_lease \gset
do $$begin
 begin perform public.capture_user_operation('draft',(select id from public.captures limit 1),1,'{"draft":{}}'); raise exception 'edit during lease unexpectedly allowed';
 exception when raise_exception then if sqlerrm<>'busy' then raise; end if; end;
end $$;
select public.capture_user_operation('release',:'owned_capture',1,jsonb_build_object('lease',:'owned_lease'));
select public.capture_user_operation('reserve',:'owned_capture',1,'{"declaredBytes":10000,"primaryWallId":"wall-north"}');
reset role;
set local role authenticated;
select set_config('request.jwt.claim.sub','22222222-2222-2222-2222-222222222222',true);
do $$begin
 if exists(select 1 from public.captures) or exists(select 1 from public.capture_photos) then raise exception 'cross-owner read'; end if;
 begin perform public.capture_user_operation('read',(select id from public.captures limit 1)); raise exception 'cross-owner RPC';
 exception when raise_exception then if sqlerrm<>'not-found' then raise; end if; end;
end $$;
reset role;
set local role anon;
do $$begin
 begin perform public.capture_user_operation('create'); raise exception 'anon key created owner';
 exception when insufficient_privilege then null; end;
end $$;
reset role;
-- Same principal can tombstone, but cannot skip physical cleanup inventory.
set local role authenticated;
select set_config('request.jwt.claim.sub','11111111-1111-1111-1111-111111111111',true);
select public.capture_user_operation('delete',:'owned_capture',2);
do $$begin if exists(select 1 from public.captures) or exists(select 1 from public.capture_photos) then raise exception 'tombstone still readable'; end if; end $$;
reset role;
set local role service_role;
select public.capture_cleanup('claim') as claimed_jobs \gset
reset role;
do $$begin
 if not exists(select 1 from private.capture_cleanup_jobs where jsonb_array_length(keys)=1 and status='working') then raise exception 'lost deletion inventory'; end if;
end $$;
rollback;
