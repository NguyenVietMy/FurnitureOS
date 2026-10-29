-- Controlled PostgreSQL contracts, not hosted Supabase acceptance.
begin;
insert into auth.users(id,is_anonymous) values('15151515-1515-1515-1515-151515151515',true),('25252525-2525-2525-2525-252525252525',false);
select set_config('request.jwt.claim.sub','15151515-1515-1515-1515-151515151515',true),set_config('request.jwt.claims','{"is_anonymous":true}',true);
set local role authenticated;
do $$begin
 begin perform public.saved_design_commit(auth.uid(),true,'private-key',repeat('a',64),'source',1,'{}',repeat('a',64),jsonb_build_object('kind','fixture','sessionExpiresAt',extract(epoch from clock_timestamp()+interval '30 minutes'))); raise exception 'public creation authority';
 exception when insufficient_privilege then null; end;
 begin insert into public.saved_designs(owner_id,idempotency_key,request_hash) values(auth.uid(),'direct-key',repeat('a',64)); raise exception 'direct insert authority';
 exception when insufficient_privilege then null; end;
end $$;
reset role;
set local role service_role;
do $$declare doc text:='{"schemaVersion":1,"status":"solved","catalogueVersion":"controlled-sql-v1","roomType":"bedroom"}'; saved jsonb; owner uuid:='15151515-1515-1515-1515-151515151515';begin
 for i in 1..100 loop
  saved:=public.saved_design_commit(owner,true,'saved-key-'||i,repeat('a',64),'source-'||i,1,doc,encode(sha256(convert_to(doc,'UTF8')),'hex'),jsonb_build_object('kind','fixture','sessionExpiresAt',extract(epoch from clock_timestamp()+interval '30 minutes')));
 end loop;
 -- Existing receipts remain valid at quota, including a lost-response replay.
 saved:=public.saved_design_commit(owner,true,'saved-key-1',repeat('a',64),'source-1',1,doc,encode(sha256(convert_to(doc,'UTF8')),'hex'),jsonb_build_object('kind','fixture','sessionExpiresAt',extract(epoch from clock_timestamp()+interval '30 minutes')));
 perform set_config('test.saved_id',saved->>'id',true);
 begin perform public.saved_design_commit(owner,true,'saved-key-101',repeat('a',64),'source-101',1,doc,encode(sha256(convert_to(doc,'UTF8')),'hex'),jsonb_build_object('kind','fixture','sessionExpiresAt',extract(epoch from clock_timestamp()+interval '30 minutes'))); raise exception 'active quota bypass';
 exception when raise_exception then if sqlerrm<>'quota' then raise;end if;end;
end $$;
reset role;
set local role authenticated;
do $$declare page jsonb; cursor text; ids text[]:='{}';begin
 loop
  page:=public.saved_design_user('list',p_cursor=>cursor);
  if jsonb_array_length(page->'items')>25 then raise exception 'unbounded page';end if;
  ids:=ids||array(select value->>'id' from jsonb_array_elements(page->'items'));
  cursor:=page->>'nextCursor';exit when cursor is null;
 end loop;
 if cardinality(ids)<>100 or (select count(distinct value) from unnest(ids) value)<>100 then raise exception 'pagination lost or duplicated records';end if;
 perform public.saved_design_user('delete',current_setting('test.saved_id')::uuid);
 perform public.saved_design_user('delete',current_setting('test.saved_id')::uuid);
 if public.saved_design_user('replay',p_key=>'saved-key-1',p_identity=>repeat('a',64))->>'status'<>'deleted' then raise exception 'deleted replay resurrected';end if;
 begin perform public.saved_design_user('replay',p_key=>'saved-key-1',p_identity=>repeat('b',64)); raise exception 'mismatched tombstone replay';
 exception when raise_exception then if sqlerrm<>'idempotency-conflict' then raise;end if;end;
end $$;
reset role;
do $$declare row public.saved_designs;begin
 select * into row from public.saved_designs where id=current_setting('test.saved_id')::uuid;
 if row.snapshot is not null or row.snapshot_sha256 is not null or row.fingerprint is not null or row.source_session is not null
  or row.source_version is not null or row.policy_version is not null or row.catalogue_version is not null or row.schema_version is not null
  or row.purge_at<>row.deleted_at+interval '25 hours' then raise exception 'deleted content retained';end if;
end $$;
set local role service_role;
do $$declare doc text:='{"schemaVersion":1,"status":"solved","catalogueVersion":"controlled-sql-v1","roomType":"bedroom"}';begin
 begin perform public.saved_design_commit('15151515-1515-1515-1515-151515151515',true,'deleted-rate-key',repeat('a',64),'source-101',1,doc,encode(sha256(convert_to(doc,'UTF8')),'hex'),jsonb_build_object('kind','fixture','sessionExpiresAt',extract(epoch from clock_timestamp()+interval '30 minutes'))); raise exception 'delete bypassed hourly rate';
 exception when raise_exception then if sqlerrm<>'quota' then raise;end if;end;
 -- Malformed/currently mismatched identity cannot use service creation.
 begin perform public.saved_design_commit('25252525-2525-2525-2525-252525252525',true,'wrong-kind-key',repeat('a',64),'source',1,doc,encode(sha256(convert_to(doc,'UTF8')),'hex'),jsonb_build_object('kind','fixture','sessionExpiresAt',extract(epoch from clock_timestamp()+interval '30 minutes'))); raise exception 'stale service identity';
 exception when raise_exception then if sqlerrm<>'not-found' then raise;end if;end;
end $$;
reset role;
-- Tombstone horizon: 24h59 remains; 25h is purged only inside creation.
update public.saved_designs set created_at=now()-interval '26 hours',deleted_at=now()-interval '24 hours 59 minutes',purge_at=now()+interval '1 minute' where id=current_setting('test.saved_id')::uuid;
set local role authenticated;
do $$begin if public.saved_design_user('replay',p_key=>'saved-key-1',p_identity=>repeat('a',64))->>'status'<>'deleted' then raise exception 'early tombstone purge';end if;end $$;
reset role;
update public.saved_designs set created_at=now()-interval '26 hours',deleted_at=now()-interval '25 hours',purge_at=now() where id=current_setting('test.saved_id')::uuid;
update public.saved_designs set created_at=now()-interval '2 hours' where deleted_at is null;
set local role service_role;
select public.saved_design_commit('15151515-1515-1515-1515-151515151515',true,'post-purge-key',repeat('c',64),'fresh-source',1,
 '{"schemaVersion":1,"status":"solved","catalogueVersion":"controlled-sql-v1","roomType":"bedroom"}',
 encode(sha256(convert_to('{"schemaVersion":1,"status":"solved","catalogueVersion":"controlled-sql-v1","roomType":"bedroom"}','UTF8')),'hex'),jsonb_build_object('kind','fixture','sessionExpiresAt',extract(epoch from clock_timestamp()+interval '30 minutes')));
reset role;
do $$begin if exists(select 1 from public.saved_designs where id=current_setting('test.saved_id')::uuid) then raise exception 'expired tombstone retained';end if;end $$;
-- Other permanent owner sees no data, cannot delete the first owner's records.
select set_config('request.jwt.claim.sub','25252525-2525-2525-2525-252525252525',true),set_config('request.jwt.claims','{"is_anonymous":false}',true);
set local role authenticated;
do $$begin
 if exists(select 1 from public.saved_designs) or jsonb_array_length(public.saved_design_user('list')->'items')<>0 then raise exception 'cross-owner read';end if;
 perform public.saved_design_user('delete',current_setting('test.saved_id')::uuid);
 begin update public.saved_designs set owner_id=auth.uid(); raise exception 'owner reassignment';exception when insufficient_privilege then null;end;
end $$;
reset role;
rollback;
