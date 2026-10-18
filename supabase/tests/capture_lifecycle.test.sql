-- Additional actual PostgreSQL proof; Storage operation helper is a local stub.
begin;
insert into auth.users(id,is_anonymous) values('11111111-1111-1111-1111-111111111111',true),('22222222-2222-2222-2222-222222222222',true);
select set_config('request.jwt.claims','{"is_anonymous":true}',true);
set local role authenticated;
select set_config('request.jwt.claim.sub','11111111-1111-1111-1111-111111111111',true);
select public.capture_user_operation('create',p_payload=>'{"consent":true}') as snapshot \gset
select (:'snapshot'::jsonb->>'id') as cid \gset
select public.capture_user_operation('reserve',:'cid',1,'{"declaredBytes":4000000,"primaryWallId":"wall-north"}') as reserved \gset
select (:'reserved'::jsonb->'photos'->0->>'id') as pid \gset
select public.capture_user_operation('lease',:'cid',2,'{"kind":"upload"}') as operation \gset
select (:'operation'::jsonb->>'lease') as lease \gset
reset role;
set local role service_role;
select public.capture_authority('finalize-photo','11111111-1111-1111-1111-111111111111',:'cid',2,:'lease',jsonb_build_object('photoId',:'pid','inputBytes',10000,'canonicalBytes',20000,'sha256',repeat('a',64),'widthPx',1280,'heightPx',960));
reset role;
insert into storage.objects(bucket_id,name,owner_id) select 'captures',object_key,owner_id::text from public.capture_photos where id=:'pid';
set local role authenticated;
select public.capture_user_operation('release',:'cid',2,jsonb_build_object('lease',:'lease'));
select set_config('test.storage.operation','object.get_authenticated',true);
do $$begin if exists(select 1 from storage.objects) then raise exception 'direct owner bytes exposed'; end if; end $$;
select set_config('test.storage.operation','object.list',true);
do $$begin if exists(select 1 from storage.objects) then raise exception 'owner listing exposed'; end if; end $$;
select set_config('test.storage.operation','object.get_authenticated',true);
select set_config('request.jwt.claim.sub','22222222-2222-2222-2222-222222222222',true);
do $$begin if exists(select 1 from storage.objects) then raise exception 'cross owner byte read'; end if; end $$;
select set_config('request.jwt.claim.sub','11111111-1111-1111-1111-111111111111',true);
select public.capture_user_operation('delete',:'cid',2);
do $$begin if exists(select 1 from storage.objects) then raise exception 'tombstone byte visibility'; end if; end $$;
reset role;
set local role service_role;
select public.capture_cleanup('claim') as jobs \gset
select (:'jobs'::jsonb->0->>'id') as job_id,(:'jobs'::jsonb->0->>'lease_token') as job_lease,(:'jobs'::jsonb->0->'keys'->>0) as byte_key \gset
-- Finishing before actual removal/progress is forbidden and failure retains inventory.
reset role;
select set_config('test.job_id',:'job_id',true),set_config('test.job_lease',:'job_lease',true);
set local role service_role;
do $$begin
 begin perform public.capture_cleanup('finish',jsonb_build_object('id',current_setting('test.job_id'),'lease',current_setting('test.job_lease'))); raise exception 'early metadata purge';
 exception when raise_exception then if sqlerrm<>'busy' then raise; end if; end;
end $$;
select public.capture_cleanup('fail',jsonb_build_object('id',:'job_id','lease',:'job_lease'));
reset role;
do $$begin
 if not exists(select 1 from private.capture_cleanup_jobs where attempts=1 and next_attempt>=now()+interval '15 minutes' and jsonb_array_length(keys)=1) then raise exception 'lost retry inventory'; end if;
 if not exists(select 1 from public.captures) then raise exception 'purged metadata during failure'; end if;
end $$;
update private.capture_cleanup_jobs set next_attempt=now();
set local role service_role;
select public.capture_cleanup('claim') as jobs \gset
select (:'jobs'::jsonb->0->>'lease_token') as new_lease \gset
reset role;
-- Only this local Storage stand-in is removed here. Production removes bytes via Storage API.
delete from storage.objects where name=:'byte_key';
set local role service_role;
select public.capture_cleanup('progress',jsonb_build_object('id',:'job_id','lease',:'new_lease','key',:'byte_key'));
select public.capture_cleanup('finish',jsonb_build_object('id',:'job_id','lease',:'new_lease'));
select public.capture_cleanup('rotate');
do $$begin if public.capture_cleanup_rotation_status() then raise exception 'rotation window did not open'; end if; end $$;
select public.capture_cleanup('scheduled');
do $$begin if not public.capture_cleanup_rotation_status() then raise exception 'previous secret not revoked'; end if; end $$;
reset role;
do $$begin if exists(select 1 from public.captures) then raise exception 'deletion not complete'; end if; end $$;
-- Accepted manifest without Storage metadata invalidates confirmation on audit.
insert into public.captures(id,owner_id,state,confirmed_revision,room_hash) values('33333333-3333-3333-3333-333333333333','11111111-1111-1111-1111-111111111111','confirmed',1,'old');
insert into public.capture_photos(id,capture_id,owner_id,object_key,primary_wall_id,state,declared_bytes) values('44444444-4444-4444-4444-444444444444','33333333-3333-3333-3333-333333333333','11111111-1111-1111-1111-111111111111','11111111-1111-1111-1111-111111111111/33333333-3333-3333-3333-333333333333/44444444-4444-4444-4444-444444444444.jpg','wall-north','accepted',1000);
set local role service_role;
select public.capture_cleanup('audit-page');
select public.capture_cleanup('audit','{"objects":[{"name":"------------------------------------/------------------------------------/------------------------------------.jpg","created_at":"2020-01-01T00:00:00Z"}],"cursor":""}');
select public.capture_cleanup('audit','{"objects":[{"name":"------------------------------------/------------------------------------/------------------------------------.jpg","created_at":"2020-01-01T00:00:00Z"}],"cursor":""}');
reset role;
do $$begin
 if not exists(select 1 from public.capture_photos where state='unavailable') then raise exception 'missing object not invalidated'; end if;
 if exists(select 1 from public.captures where confirmed_revision is not null) then raise exception 'missing object retained confirmation'; end if;
 if not exists(select 1 from private.capture_cleanup_jobs where reason='unrecognized-path' and status='attention-required') then raise exception 'unknown path not retained'; end if;
 if (select count(*) from private.capture_cleanup_jobs where reason='unrecognized-path')<>1 then raise exception 'duplicate unknown-path attention'; end if;
 if not exists(select 1 from private.capture_cleanup_jobs where reason='unrecognized-path' and attention_path='------------------------------------/------------------------------------/------------------------------------.jpg' and attention_fingerprint=encode(sha256(convert_to(attention_path,'UTF8')),'hex') and keys='[]') then raise exception 'attention identity missing or unsafe'; end if;
end $$;
-- Removal/retry churn cannot reset lifetime reservation or analysis budgets.
insert into private.capture_counters(capture_id,input_reserved,analysis_total) values('33333333-3333-3333-3333-333333333333',32000000,16);
set local role authenticated;
select set_config('request.jwt.claim.sub','11111111-1111-1111-1111-111111111111',true);
do $$begin
 begin perform public.capture_user_operation('reserve','33333333-3333-3333-3333-333333333333',2,'{"declaredBytes":1000,"primaryWallId":"wall-east"}'); raise exception 'lifetime input budget reset';
 exception when raise_exception then if sqlerrm<>'quota' then raise; end if; end;
end $$;
reset role;
rollback;
