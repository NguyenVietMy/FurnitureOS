-- Actual PostgreSQL correction contracts; auth/storage fixtures are explicitly local.
begin;
insert into auth.users(id,is_anonymous) values('11111111-1111-1111-1111-111111111111',true);
select set_config('request.jwt.claim.sub','11111111-1111-1111-1111-111111111111',true),set_config('request.jwt.claims','{"is_anonymous":true}',true);
set local role authenticated;
select public.capture_user_operation('create',p_payload=>'{"consent":true}') as first_snapshot \gset
select set_config('test.status_capture',:'first_snapshot'::jsonb->>'id',true);
reset role;
update public.captures set state='confirmed',confirmed_revision=1,room_hash=repeat('a',64),validated_room='{"privateRoom":"secret"}',
 draft='{"widthM":6,"privateDraft":"secret"}',calibrations='[{"privateCalibration":"secret"}]' where id=current_setting('test.status_capture')::uuid;
set local role authenticated;
do $$begin
 begin perform public.capture_user_operation('delete-status',current_setting('test.status_capture')::uuid); raise exception 'active status exposed';
 exception when raise_exception then if sqlerrm<>'not-found' then raise; end if; end;
end $$;
reset role;
update public.captures set created_at=now()-interval '25 hours',expires_at=now()-interval '1 hour' where id=current_setting('test.status_capture')::uuid;
do $$begin if private.capture_json(current_setting('test.status_capture')::uuid) is not null then raise exception 'general snapshot leaks expired row'; end if; end $$;
set local role authenticated;
do $$begin
 begin perform public.capture_user_operation('delete-status',current_setting('test.status_capture')::uuid); raise exception 'expired status exposed';
 exception when raise_exception then if sqlerrm<>'not-found' then raise; end if; end;
end $$;
reset role;
set local role service_role;
select public.capture_cleanup('claim');
reset role;
set local role authenticated;
do $$declare status jsonb;begin
 for i in 1..2 loop
  status:=public.capture_user_operation('delete-status',current_setting('test.status_capture')::uuid);
  if status is distinct from jsonb_build_object('id',current_setting('test.status_capture'),'state','deleting','inaccessible',true,'cleanupStatus','pending') then raise exception 'private data in lifecycle poll'; end if;
 end loop;
end $$;
-- Active data for anonymous-only direct Data API/Storage and semantic invalidation tests.
select public.capture_user_operation('create',p_payload=>'{"consent":true}') as second_snapshot \gset
select set_config('test.semantic_capture',:'second_snapshot'::jsonb->>'id',true);
reset role;
update public.captures set state='confirmed',confirmed_revision=1,room_hash=repeat('b',64),validated_room='{"oldRoom":true}',
 draft='{"widthM":6,"depthM":4,"heightM":2.5,"dimensionsConfirmed":true,"openings":[{"id":"user-corrected-window","widthM":0.7}],"wallReviews":["wall-north","wall-east","wall-south","wall-west"],"furnitureAcknowledged":true}' where id=current_setting('test.semantic_capture')::uuid;
insert into public.capture_photos(id,capture_id,owner_id,object_key,primary_wall_id,observed_wall_ids,state,declared_bytes,sha256)
 values('44444444-4444-4444-4444-444444444444',current_setting('test.semantic_capture')::uuid,'11111111-1111-1111-1111-111111111111',
 '11111111-1111-1111-1111-111111111111/'||current_setting('test.semantic_capture')||'/44444444-4444-4444-4444-444444444444.jpg','wall-north','["wall-east"]','accepted',1000,repeat('a',64));
insert into storage.objects(bucket_id,name) select 'captures',object_key from public.capture_photos;
select set_config('test.storage.operation','object.get_authenticated',true);
set local role authenticated;
do $$begin if (select count(*) from public.captures)<>1 or (select count(*) from public.capture_photos)<>1 or exists(select 1 from storage.objects) then raise exception 'metadata authority or server-only byte boundary broken'; end if; end $$;
-- Missing, false, string-true and mutable metadata cannot impersonate a signed anonymous claim.
do $$declare claims jsonb;begin
 for claims in select value from jsonb_array_elements('[{}, {"is_anonymous":false,"user_metadata":{"is_anonymous":true}}, {"is_anonymous":"true"}]') loop
  perform set_config('request.jwt.claims',claims::text,true);
  if private.capture_anonymous_owner() or exists(select 1 from public.captures) or exists(select 1 from public.capture_photos) or exists(select 1 from storage.objects) then raise exception 'nonanonymous signed claim gained access'; end if;
  begin perform public.capture_user_operation('create',p_payload=>'{"consent":true}'); raise exception 'nonanonymous RPC create';
  exception when raise_exception then if sqlerrm<>'not-found' then raise; end if; end;
 end loop;
end $$;
select set_config('request.jwt.claims','{"is_anonymous":true}',true);
reset role;
-- Even an old still-signed anonymous token cannot bypass a current permanent Auth row.
update auth.users set is_anonymous=false;
set local role authenticated;
do $$declare action text;begin
 if private.capture_anonymous_owner() or exists(select 1 from public.captures) or exists(select 1 from public.capture_photos) or exists(select 1 from storage.objects) then raise exception 'permanent current identity gained access'; end if;
 foreach action in array array['create','read','delete-status'] loop
  begin perform public.capture_user_operation(action,current_setting('test.semantic_capture')::uuid,1,'{"consent":true}'); raise exception 'permanent RPC gained access';
  exception when raise_exception then if sqlerrm<>'not-found' then raise; end if; end;
 end loop;
end $$;
reset role;
set local role service_role;
do $$begin
 begin perform public.capture_authority('confirm','11111111-1111-1111-1111-111111111111',current_setting('test.semantic_capture')::uuid,1,null,'{}'); raise exception 'permanent authority gained access';
 exception when raise_exception then if sqlerrm<>'not-found' then raise; end if; end;
end $$;
reset role;
update auth.users set is_anonymous=true;
set local role authenticated;
select public.capture_user_operation('lease',current_setting('test.semantic_capture')::uuid,1,'{"kind":"generation"}') as generation_lease \gset
select public.capture_user_operation('lease',current_setting('test.semantic_capture')::uuid,1,'{"kind":"vision"}') as vision_lease \gset
select set_config('test.generation_lease',:'generation_lease'::jsonb->>'lease',true),set_config('test.vision_lease',:'vision_lease'::jsonb->>'lease',true);
reset role;
set local role service_role;
select public.capture_authority('begin-analysis','11111111-1111-1111-1111-111111111111',current_setting('test.semantic_capture')::uuid,1,current_setting('test.vision_lease')::uuid,'{"photoId":"44444444-4444-4444-4444-444444444444"}');
select public.capture_authority('semantics','11111111-1111-1111-1111-111111111111',current_setting('test.semantic_capture')::uuid,1,current_setting('test.vision_lease')::uuid,
 jsonb_build_object('photoId','44444444-4444-4444-4444-444444444444','sha256',repeat('a',64),'semantics','{"openings":[{"id":"new-evidence","wallId":"wall-north"}],"detectedFurniture":"unknown","observation":"partial"}'::jsonb));
reset role;
do $$declare c public.captures;begin
 select * into c from public.captures where id=current_setting('test.semantic_capture')::uuid;
 if c.revision<>2 or c.state<>'draft' or c.confirmed_revision is not null or c.room_hash is not null or c.validated_room is not null then raise exception 'semantic result retained confirmation'; end if;
 if c.draft->'wallReviews'<>'["wall-south","wall-west"]'::jsonb or c.draft->'furnitureAcknowledged'<>'false'::jsonb then raise exception 'new evidence retained explicit reviews'; end if;
 if c.draft->'widthM'<>'6'::jsonb or c.draft->'dimensionsConfirmed'<>'true'::jsonb or c.draft->'openings'<>'[{"id":"user-corrected-window","widthM":0.7}]'::jsonb then raise exception 'semantic result overwrote corrections'; end if;
end $$;
set local role authenticated;
do $$begin
 begin perform public.capture_user_operation('assert',current_setting('test.semantic_capture')::uuid,1,jsonb_build_object('lease',current_setting('test.generation_lease'))); raise exception 'old generation lease published';
 exception when raise_exception then if sqlerrm<>'stale-capture' then raise; end if; end;
end $$;
select public.capture_user_operation('release',current_setting('test.semantic_capture')::uuid,1,jsonb_build_object('lease',current_setting('test.vision_lease')));
-- Old generation still counts toward concurrency, but cannot block editing the new revision.
select public.capture_user_operation('draft',current_setting('test.semantic_capture')::uuid,2,'{"draft":{"widthM":7}}');
select public.capture_user_operation('release',current_setting('test.semantic_capture')::uuid,1,jsonb_build_object('lease',current_setting('test.generation_lease')));
reset role;
do $$begin if exists(select 1 from private.capture_operations) then raise exception 'old bounded lease release stranded'; end if; end $$;
-- A second analysis arriving after a later explicit correction must fail atomically.
set local role authenticated;
select public.capture_user_operation('lease',current_setting('test.semantic_capture')::uuid,3,'{"kind":"vision"}') as late_lease \gset
select set_config('test.late_lease',:'late_lease'::jsonb->>'lease',true);
reset role;
set local role service_role;
select public.capture_authority('begin-analysis','11111111-1111-1111-1111-111111111111',current_setting('test.semantic_capture')::uuid,3,current_setting('test.late_lease')::uuid,'{"photoId":"44444444-4444-4444-4444-444444444444"}');
reset role;
set local role authenticated;
select public.capture_user_operation('release',current_setting('test.semantic_capture')::uuid,3,jsonb_build_object('lease',current_setting('test.late_lease')));
select public.capture_user_operation('draft',current_setting('test.semantic_capture')::uuid,3,'{"draft":{"widthM":8,"wallReviews":["wall-north"]}}');
reset role;
set local role service_role;
do $$begin
 begin perform public.capture_authority('semantics','11111111-1111-1111-1111-111111111111',current_setting('test.semantic_capture')::uuid,3,current_setting('test.late_lease')::uuid,
  jsonb_build_object('photoId','44444444-4444-4444-4444-444444444444','sha256',repeat('a',64),'semantics','{"openings":[],"detectedFurniture":"absent","observation":"complete"}'::jsonb)); raise exception 'late semantics overwrote correction';
 exception when raise_exception then if sqlerrm<>'stale-capture' then raise; end if; end;
end $$;
reset role;
do $$declare c public.captures;begin
 select * into c from public.captures where id=current_setting('test.semantic_capture')::uuid;
 if c.revision<>4 or c.draft is distinct from '{"widthM":8,"wallReviews":["wall-north"]}'::jsonb then raise exception 'late result mutated current draft'; end if;
 if (select semantics->>'detectedFurniture' from public.capture_photos where capture_id=c.id)<>'unknown' then raise exception 'late result installed evidence'; end if;
end $$;
rollback;

-- Reanalysis must revoke reviews for BOTH stored and replacement proposal walls.
-- Each isolated owner/photo uses the real begin-analysis + semantics authority twice.
begin;
select set_config('request.jwt.claims','{"is_anonymous":true}',true);
do $$declare
 scenario record; owner uuid; cid uuid; pid uuid; lease_id uuid; revision integer;
 snapshot jsonb; old_proposal jsonb; new_proposal jsonb; corrected jsonb; calibration jsonb;
 actual public.captures;
begin
 for scenario in select * from (values
  ('removed','wall-south','none','["wall-east"]'::jsonb,'["wall-west"]'::jsonb),
  ('moved','wall-south','wall-east','[]'::jsonb,'["wall-west"]'::jsonb),
  ('old-unknown-resolved',null,'wall-east','["wall-east"]'::jsonb,'[]'::jsonb),
  ('old-unknown-empty',null,'none','["wall-east"]'::jsonb,'[]'::jsonb),
  ('new-unknown','wall-south',null,'["wall-east"]'::jsonb,'[]'::jsonb),
  ('both-unknown',null,null,'["wall-east"]'::jsonb,'[]'::jsonb)
 ) as cases(label,old_wall,new_wall,observed,expected_reviews) loop
  owner:=gen_random_uuid(); pid:=gen_random_uuid();
  insert into auth.users(id,is_anonymous) values(owner,true);
  perform set_config('request.jwt.claim.sub',owner::text,true);
  execute 'set local role authenticated';
  snapshot:=public.capture_user_operation('create',p_payload=>'{"consent":true}');
  cid:=(snapshot->>'id')::uuid;
  execute 'reset role';
  insert into public.capture_photos(id,capture_id,owner_id,object_key,primary_wall_id,observed_wall_ids,state,declared_bytes,sha256)
   values(pid,cid,owner,owner::text||'/'||cid::text||'/'||pid::text||'.jpg','wall-north',scenario.observed,'accepted',1000,repeat('c',64));
  old_proposal:=jsonb_build_object('openings',jsonb_build_array(jsonb_build_object('id','old-opening','wallId',scenario.old_wall)),
   'detectedFurniture','absent','observation','partial');
  new_proposal:=jsonb_build_object('openings',case when scenario.new_wall='none' then '[]'::jsonb
   else jsonb_build_array(jsonb_build_object('id','new-opening','wallId',scenario.new_wall)) end,
   'detectedFurniture','absent','observation','partial');
  execute 'set local role authenticated';
  lease_id:=(public.capture_user_operation('lease',cid,1,'{"kind":"vision"}')->>'lease')::uuid;
  execute 'reset role';
  execute 'set local role service_role';
  perform public.capture_authority('begin-analysis',owner,cid,1,lease_id,jsonb_build_object('photoId',pid));
  snapshot:=public.capture_authority('semantics',owner,cid,1,lease_id,jsonb_build_object('photoId',pid,'sha256',repeat('c',64),'semantics',old_proposal));
  execute 'reset role';
  if snapshot->'photos'->0->'semantics' is distinct from old_proposal then raise exception '%: old evidence not stored',scenario.label; end if;
  execute 'set local role authenticated';
  perform public.capture_user_operation('release',cid,1,jsonb_build_object('lease',lease_id));
  corrected:=jsonb_build_object('roomType','bedroom','topology','rectangle','widthM',6.4,'depthM',4.2,'heightM',2.5,'dimensionsConfirmed',true,
   'wallReviews','["wall-north","wall-east","wall-south","wall-west"]'::jsonb,'furnitureAcknowledged',true,
   'openings','[{"id":"manual-window","wallId":"wall-west","kind":"window","widthM":0.7,"reviewed":true}]'::jsonb,
   'dimensionEvidence',jsonb_build_array(jsonb_build_object('field','widthM','valueM',6.4,'photoId',pid,'photoHash',repeat('c',64),'overrideReason','Verified measured correction')));
  snapshot:=public.capture_user_operation('draft',cid,2,jsonb_build_object('draft',corrected));
  revision:=(snapshot->>'revision')::integer;
  lease_id:=(public.capture_user_operation('lease',cid,revision,'{"kind":"calibration"}')->>'lease')::uuid;
  execute 'reset role';
  calibration:=jsonb_build_object('request',jsonb_build_object('photoId',pid,'photoHash',repeat('c',64)),'result','{"status":"provisional","method":"coplanar-rectangle-homography-v1"}'::jsonb);
  execute 'set local role service_role';
  perform public.capture_authority('calibration',owner,cid,revision,lease_id,calibration);
  execute 'reset role';
  execute 'set local role authenticated';
  perform public.capture_user_operation('release',cid,revision,jsonb_build_object('lease',lease_id));
  lease_id:=(public.capture_user_operation('lease',cid,revision,'{"kind":"confirm"}')->>'lease')::uuid;
  execute 'reset role';
  execute 'set local role service_role';
  perform public.capture_authority('confirm',owner,cid,revision,lease_id,'{"roomHash":"previous-confirmation","room":{"previousRoom":true}}');
  execute 'reset role';
  execute 'set local role authenticated';
  perform public.capture_user_operation('release',cid,revision,jsonb_build_object('lease',lease_id));
  lease_id:=(public.capture_user_operation('lease',cid,revision,'{"kind":"vision"}')->>'lease')::uuid;
  execute 'reset role';
  execute 'set local role service_role';
  perform public.capture_authority('begin-analysis',owner,cid,revision,lease_id,jsonb_build_object('photoId',pid));
  snapshot:=public.capture_authority('semantics',owner,cid,revision,lease_id,jsonb_build_object('photoId',pid,'sha256',repeat('c',64),'semantics',new_proposal));
  execute 'reset role';
  select * into actual from public.captures where id=cid;
  if actual.draft->'wallReviews' is distinct from scenario.expected_reviews then
   raise exception '%: stale old/new wall review; got %, expected %',scenario.label,actual.draft->'wallReviews',scenario.expected_reviews;
  end if;
  if actual.draft-'wallReviews' is distinct from corrected-'wallReviews' or actual.calibrations is distinct from jsonb_build_array(calibration) then
   raise exception '%: manual correction/dimension provenance overwritten',scenario.label;
  end if;
  if actual.revision<>revision+1 or actual.state<>'draft' or actual.confirmed_revision is not null or actual.validated_room is not null or actual.room_hash is not null then
   raise exception '%: stale confirmation survived',scenario.label;
  end if;
  if snapshot->'photos'->0->'semantics' is distinct from new_proposal or (snapshot->'photos'->0->>'analysisAttempts')::integer<>2 then
   raise exception '%: replacement evidence or two-attempt contract broken',scenario.label;
  end if;
  execute 'set local role authenticated';
  perform public.capture_user_operation('release',cid,revision,jsonb_build_object('lease',lease_id));
  execute 'reset role';
  raise notice 'PASS prior/new wall scenario: %',scenario.label;
 end loop;
 if exists(select 1 from private.capture_operations) then raise exception 'replacement result stranded old lease'; end if;
end $$;
rollback;
