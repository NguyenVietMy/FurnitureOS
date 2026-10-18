-- Local PostgreSQL contract only; real Auth/Storage/CDN acceptance is separate.
begin;
insert into auth.users(id,is_anonymous) values('11111111-1111-1111-1111-111111111111',true),('22222222-2222-2222-2222-222222222222',true);
select set_config('request.jwt.claims','{"is_anonymous":true}',true);
select set_config('request.jwt.claim.sub','11111111-1111-1111-1111-111111111111',true);
do $$
declare
 snapshot jsonb; cid uuid; rev integer; pid uuid; lease_id uuid; field text; wall text;
 desired jsonb; mutated jsonb; actual public.captures; before_photo public.capture_photos;
 walls jsonb:='["wall-north","wall-notch-vertical","wall-notch-horizontal","wall-east","wall-south","wall-west"]';
begin
 execute 'set local role authenticated';
 snapshot:=public.capture_user_operation('create',p_payload=>'{"consent":true}');
 cid:=(snapshot->>'id')::uuid;
 desired:=jsonb_build_object('topology','L-shaped','roomType','bedroom','widthM',6,'depthM',5,'heightM',2.7,'notchWidthM',2,'notchDepthM',2,
  'dimensionsConfirmed',true,'wallReviews',walls,'furnitureAcknowledged',true,
  'dimensionEvidence','[]'::jsonb,'openings','[{"id":"window","wallId":"wall-west","reviewed":true,"widthM":0.5}]'::jsonb);
 snapshot:=public.capture_user_operation('draft',cid,1,jsonb_build_object('draft',desired));
 if snapshot->'draft'->'dimensionsConfirmed'<>'false' or snapshot->'draft'->'wallReviews'<>'[]'
    or snapshot->'draft'->'openings'->0->'wallId'<>'null' then raise exception 'shape mutation accepted stale flags'; end if;
 rev:=(snapshot->>'revision')::integer;
 snapshot:=public.capture_user_operation('draft',cid,rev,jsonb_build_object('draft',desired));
 if snapshot->'draft'->'dimensionsConfirmed'<>'true' then raise exception 'explicit saved confirmation rejected'; end if;
 rev:=(snapshot->>'revision')::integer;
 for wall in select jsonb_array_elements_text(walls) loop
  snapshot:=public.capture_user_operation('reserve',cid,rev,jsonb_build_object('declaredBytes',1000,'primaryWallId',wall));
  rev:=(snapshot->>'revision')::integer;
 end loop;
 if jsonb_array_length(snapshot->'photos')<>6 then raise exception 'six primary photos not reserved'; end if;
 pid:=(snapshot->'photos'->0->>'id')::uuid;
 snapshot:=public.capture_user_operation('associate',cid,rev,jsonb_build_object('photoId',pid,'primaryWallId','wall-north','observedWallIds',walls));
 rev:=(snapshot->>'revision')::integer;
 if snapshot->'photos'->0->'observedWallIds'<>walls then raise exception 'six observed walls lost'; end if;
 begin perform public.capture_user_operation('associate',cid,rev,jsonb_build_object('photoId',pid,'primaryWallId','invented-wall','observedWallIds','[]'::jsonb));raise exception 'invalid primary accepted';
 exception when raise_exception then if sqlerrm<>'invalid-wall' then raise;end if;end;
 begin perform public.capture_user_operation('associate',cid,rev,jsonb_build_object('photoId',pid,'primaryWallId','wall-north','observedWallIds',walls||'["wall-north"]'::jsonb));raise exception 'seven observations accepted';
 exception when raise_exception then if sqlerrm<>'invalid-wall' then raise;end if;end;

 foreach field in array array['widthM','depthM','heightM','notchWidthM','notchDepthM'] loop
  snapshot:=public.capture_user_operation('draft',cid,rev,jsonb_build_object('draft',desired));
  rev:=(snapshot->>'revision')::integer;
  snapshot:=public.capture_user_operation('draft',cid,rev,jsonb_build_object('draft',desired));
  rev:=(snapshot->>'revision')::integer;
  lease_id:=(public.capture_user_operation('lease',cid,rev,'{"kind":"confirm"}')->>'lease')::uuid;
  execute 'set local role service_role';
  perform public.capture_authority('confirm','11111111-1111-1111-1111-111111111111',cid,rev,lease_id,'{"roomHash":"old-room-hash","room":{"confirmed":true}}');
  execute 'set local role authenticated';
  perform public.capture_user_operation('release',cid,rev,jsonb_build_object('lease',lease_id));
  mutated:=jsonb_set(desired,array[field],to_jsonb((desired->>field)::numeric+0.1));
  snapshot:=public.capture_user_operation('draft',cid,rev,jsonb_build_object('draft',mutated));
  rev:=(snapshot->>'revision')::integer;
  if snapshot->>'state'<>'draft' or snapshot->'roomHash'<>'null' or snapshot->'confirmedRevision'<>'null'
     or snapshot->'draft'->'dimensionsConfirmed'<>'false' or snapshot->'draft'->'wallReviews'<>'[]'
     or snapshot->'draft'->'openings'->0->'reviewed'<>'false'
     or snapshot->'draft'->'openings'->0->>'wallId'<>'wall-west'
     or snapshot->'draft'->field<>mutated->field then raise exception '% transition retained stale authority/reviews',field; end if;
  snapshot:=public.capture_user_operation('draft',cid,rev,jsonb_build_object('draft',mutated));
  rev:=(snapshot->>'revision')::integer;
  if snapshot->'draft'->'dimensionsConfirmed'<>'true' or snapshot->'draft'->'wallReviews'<>walls then raise exception '% unchanged review rejected',field;end if;
 end loop;

 -- Restore L and seed independently observable old proposal/provenance state.
 snapshot:=public.capture_user_operation('draft',cid,rev,jsonb_build_object('draft',desired));rev:=(snapshot->>'revision')::integer;
 snapshot:=public.capture_user_operation('draft',cid,rev,jsonb_build_object('draft',desired));rev:=(snapshot->>'revision')::integer;
 execute 'reset role';
 update public.capture_photos set state='accepted',sha256=repeat('a',64),analysis_status='complete',analysis_attempts=1,
  observed_wall_ids='["wall-west"]',semantics='{"openings":[{"wallId":"wall-notch-vertical"}],"detectedFurniture":"absent"}' where id=pid;
 execute 'set local role authenticated';
 lease_id:=(public.capture_user_operation('lease',cid,rev,'{"kind":"vision"}')->>'lease')::uuid;
 execute 'set local role service_role';
 perform public.capture_authority('begin-analysis','11111111-1111-1111-1111-111111111111',cid,rev,lease_id,jsonb_build_object('photoId',pid));
 snapshot:=public.capture_authority('semantics','11111111-1111-1111-1111-111111111111',cid,rev,lease_id,
   jsonb_build_object('photoId',pid,'sha256',repeat('a',64),'semantics','{"openings":[],"detectedFurniture":"absent"}'::jsonb));
 if snapshot->'draft'->'wallReviews'<>'["wall-notch-horizontal","wall-east","wall-south"]'::jsonb then raise exception 'removed notch proposal review survived';end if;
 rev:=(snapshot->>'revision')::integer;
 execute 'set local role authenticated';
 perform public.capture_user_operation('release',cid,rev-1,jsonb_build_object('lease',lease_id));
 snapshot:=public.capture_user_operation('draft',cid,rev,jsonb_build_object('draft',desired));rev:=(snapshot->>'revision')::integer;
 execute 'reset role';
 update public.capture_photos set analysis_attempts=0 where id=pid;
 execute 'set local role authenticated';
 lease_id:=(public.capture_user_operation('lease',cid,rev,'{"kind":"vision"}')->>'lease')::uuid;
 execute 'set local role service_role';
 perform public.capture_authority('begin-analysis','11111111-1111-1111-1111-111111111111',cid,rev,lease_id,jsonb_build_object('photoId',pid));
 snapshot:=public.capture_authority('semantics','11111111-1111-1111-1111-111111111111',cid,rev,lease_id,
   jsonb_build_object('photoId',pid,'sha256',repeat('a',64),'semantics','{"openings":[{"wallId":null}],"detectedFurniture":"unknown"}'::jsonb));
 if snapshot->'draft'->'wallReviews'<>'[]'::jsonb or snapshot->'draft'->'furnitureAcknowledged'<>'false' then raise exception 'unknown semantics did not clear all six walls';end if;
 rev:=(snapshot->>'revision')::integer;
 execute 'set local role authenticated';
 perform public.capture_user_operation('release',cid,rev-1,jsonb_build_object('lease',lease_id));
 execute 'reset role';
 select * into before_photo from public.capture_photos where id=pid;
 update public.captures set calibrations='[{"preservedUntilShapeChange":true}]',
  draft=desired||jsonb_build_object('dimensionEvidence',jsonb_build_array(jsonb_build_object('field','widthM','valueM',6,'photoId',pid,'photoHash',repeat('a',64),'overrideReason',''))) where id=cid;
 execute 'set local role authenticated';
 mutated:=desired||'{"topology":"rectangle","notchWidthM":99,"notchDepthM":99}'::jsonb;
 snapshot:=public.capture_user_operation('draft',cid,rev,jsonb_build_object('draft',mutated));rev:=(snapshot->>'revision')::integer;
 if snapshot->'draft'->'widthM'<>'null' or snapshot->'draft'->'notchWidthM'<>'null'
    or snapshot->'draft'->'dimensionEvidence'<>'[]' or snapshot->'calibrations'<>'[]'
    or snapshot->'draft'->'openings'->0->'wallId'<>'null' then raise exception 'shape retained incompatible calibration/Opening association';end if;
 execute 'reset role';
 if exists(select 1 from public.capture_photos where capture_id=cid and (semantics is not null or observed_wall_ids<>'[]' or analysis_status<>'unknown'))
    or not exists(select 1 from public.capture_photos where capture_id=cid and primary_wall_id='wall-notch-vertical')
    or not exists(select 1 from public.capture_photos where id=pid and analysis_attempts=before_photo.analysis_attempts and sha256=before_photo.sha256) then
  raise exception 'shape silently discarded bytes/primary ids or reset attempts';end if;
 execute 'set local role authenticated';
 mutated:=snapshot->'draft'||'{"notchWidthM":-99,"notchDepthM":123,"dimensionsConfirmed":true,"wallReviews":["wall-north"]}'::jsonb;
 snapshot:=public.capture_user_operation('draft',cid,rev,jsonb_build_object('draft',mutated));rev:=(snapshot->>'revision')::integer;
 if snapshot->'draft'->'notchWidthM'<>'null' or snapshot->'draft'->'dimensionsConfirmed'<>'true' then raise exception 'inactive notch changed rectangle metric truth';end if;
 begin perform public.capture_user_operation('reserve',cid,rev,'{"declaredBytes":1000,"primaryWallId":"wall-notch-vertical"}');raise exception 'rectangle accepted notch primary';
 exception when raise_exception then if sqlerrm<>'invalid-wall' then raise;end if;end;
 execute 'reset role';
 perform set_config('request.jwt.claim.sub','22222222-2222-2222-2222-222222222222',true);
 execute 'set local role authenticated';
 if exists(select 1 from public.captures where id=cid) then raise exception 'cross-owner read';end if;
 begin perform public.capture_user_operation('read',cid);raise exception 'cross-owner RPC';exception when raise_exception then if sqlerrm<>'not-found' then raise;end if;end;
 begin update public.capture_photos set primary_wall_id='wall-north';raise exception 'direct mutation';exception when insufficient_privilege then null;end;
 execute 'reset role';
 raise notice 'Ticket10 SQL: six-wall reserve/associate, all five dimensions, stale flags, topology/provenance, unknown/removed semantics, owner/denial passed';
end $$;
rollback;
