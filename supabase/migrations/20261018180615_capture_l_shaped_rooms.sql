-- Ticket 10 additive upgrade. Earlier applied migration bytes remain immutable.
-- No cutover/Storage policy change and no deletion of existing Capture state.
begin;
alter table public.capture_photos drop constraint capture_photos_primary_wall_id_check;
alter table public.capture_photos add constraint capture_photos_primary_wall_id_check
 check(primary_wall_id in ('wall-north','wall-east','wall-south','wall-west','wall-notch-vertical','wall-notch-horizontal'));
alter table public.capture_photos drop constraint capture_photos_observed_wall_ids_check;
alter table public.capture_photos add constraint capture_photos_observed_wall_ids_check
 check(jsonb_typeof(observed_wall_ids)='array' and jsonb_array_length(observed_wall_ids)<=6
       and observed_wall_ids <@ '["wall-north","wall-east","wall-south","wall-west","wall-notch-vertical","wall-notch-horizontal"]'::jsonb);

create function private.capture_active_walls(topology text) returns jsonb
language sql immutable security invoker set search_path='' as $$
 select case when topology='L-shaped'
 then '["wall-north","wall-notch-vertical","wall-notch-horizontal","wall-east","wall-south","wall-west"]'::jsonb
 else '["wall-north","wall-east","wall-south","wall-west"]'::jsonb end
$$;
revoke all on function private.capture_active_walls(text) from public,anon,authenticated;
-- This helper is used only inside the existing definer transaction authority.

create or replace function private.capture_user(p_action text,p_capture uuid,p_revision integer,p_payload jsonb) returns jsonb
language plpgsql security definer set search_path='' as $$
declare owner uuid:=auth.uid(); c public.captures; photo uuid; lease_id uuid; lease_seconds integer; v_kind text; declared integer; evidence jsonb; next_draft jsonb; active jsonb; field text; topology_changed boolean; dimensions_changed boolean;
begin
 if owner is null or not private.capture_anonymous_owner() then raise exception 'not-found'; end if;
 if octet_length(p_payload::text)>32768 then raise exception 'quota'; end if;
 perform pg_advisory_xact_lock(hashtextextended(owner::text,0));
 if p_action='create' then
  if p_payload->'consent' is distinct from 'true'::jsonb then raise exception 'not-found'; end if;
  if (select count(*) from public.captures where owner_id=owner and state<>'deleting' and expires_at>now())>=4 or
     (select count(*) from private.capture_events where owner_id=owner and kind='create' and created_at>now()-interval '1 hour')>=4 then raise exception 'quota'; end if;
  insert into public.captures(owner_id) values(owner) returning * into c;
  insert into private.capture_counters(capture_id) values(c.id);
  insert into private.capture_events(owner_id,kind) values(owner,'create');
  return private.capture_json(c.id);
 end if;
 select * into c from public.captures where id=p_capture and owner_id=owner for update;
 if not found then raise exception 'not-found'; end if;
 if p_action='delete-status' then
  if c.state<>'deleting' then raise exception 'not-found'; end if;
  return private.capture_deletion_json(c.id);
 end if;
 if c.state='deleting' or c.expires_at<=now() then raise exception 'not-found'; end if;
 if p_action='read' then return private.capture_json(c.id); end if;
 if p_action='release' then
  delete from private.capture_operations where id=(p_payload->>'lease')::uuid and owner_id=owner and capture_id=c.id;
  return '{}'::jsonb;
 end if;
 if c.revision<>p_revision then raise exception 'stale-capture'; end if;
 if p_action='assert' then
  if not exists(select 1 from private.capture_operations where id=(p_payload->>'lease')::uuid and capture_id=c.id and owner_id=owner and revision=c.revision and expires_at>now()) then raise exception 'lease-expired'; end if;
  if p_payload->>'roomHash' is not null and c.room_hash is distinct from p_payload->>'roomHash' then raise exception 'stale-capture'; end if;
  return '{}'::jsonb;
 end if;
 if p_action='delete' then perform private.capture_enqueue(c.id,'manual'); return private.capture_json(c.id); end if;
 if p_action='lease' then
  v_kind:=p_payload->>'kind'; lease_seconds:=coalesce((p_payload->>'seconds')::integer,120);
  if v_kind not in ('upload','vision','generation','session','confirm','calibration','photo-read') or lease_seconds<1 or lease_seconds>300 then raise exception 'quota'; end if;
  if (select count(*) from private.capture_operations where owner_id=owner and expires_at>now())>=2 or
    (v_kind in ('upload','vision') and exists(select 1 from private.capture_operations where owner_id=owner and private.capture_operations.kind=v_kind and expires_at>now())) then raise exception 'busy'; end if;
  insert into private.capture_operations(owner_id,capture_id,revision,kind,expires_at) values(owner,c.id,c.revision,v_kind,least(c.expires_at,now()+make_interval(secs=>lease_seconds))) returning id into lease_id;
  return jsonb_build_object('lease',lease_id);
 end if;
 if exists(select 1 from private.capture_operations where capture_id=c.id and revision=c.revision and expires_at>now()) then raise exception 'busy'; end if;
 if p_action='draft' then
  next_draft:=p_payload->'draft';
  if jsonb_typeof(next_draft) is distinct from 'object' then raise exception 'invalid-draft'; end if;
  topology_changed:=coalesce(c.draft->>'topology','') is distinct from coalesce(next_draft->>'topology','');
  active:=private.capture_active_walls(next_draft->>'topology');
  if next_draft->>'topology' is distinct from 'L-shaped' then
   next_draft:=next_draft||'{"notchWidthM":null,"notchDepthM":null}'::jsonb;
  end if;
  dimensions_changed:=false;
  foreach field in array case when next_draft->>'topology'='L-shaped'
   then array['widthM','depthM','heightM','notchWidthM','notchDepthM']
   else array['widthM','depthM','heightM'] end loop
   if coalesce(c.draft->field,'null'::jsonb) is distinct from coalesce(next_draft->field,'null'::jsonb) then
    dimensions_changed:=true;
   end if;
  end loop;
  if topology_changed then
   -- Remove only unchanged applied provisional values; explicit manual values survive.
   for evidence in select value from jsonb_array_elements(coalesce(c.draft->'dimensionEvidence','[]')) loop
    if evidence->>'field' in ('widthM','depthM','heightM','notchWidthM','notchDepthM')
       and btrim(coalesce(evidence->>'overrideReason',''))=''
       and c.draft->(evidence->>'field')=evidence->'valueM'
       and next_draft->(evidence->>'field')=evidence->'valueM' then
     next_draft:=jsonb_set(next_draft,array[evidence->>'field'],'null');
    end if;
   end loop;
   next_draft:=next_draft||'{"dimensionEvidence":[]}'::jsonb;
   update public.captures set calibrations='[]' where id=c.id;
   update public.capture_photos set semantics=null,observed_wall_ids='[]',analysis_status='unknown' where capture_id=c.id;
  end if;
  if topology_changed or dimensions_changed then
   -- All dimensions, including height, conservatively affect every wall/Opening.
   -- Never accept stale flags supplied in the mutation that changes metric truth.
   next_draft:=next_draft||'{"dimensionsConfirmed":false,"wallReviews":[]}'::jsonb;
   next_draft:=jsonb_set(next_draft,'{openings}',coalesce(
    (select jsonb_agg(case when topology_changed then value||'{"reviewed":false,"wallId":null}'::jsonb
                     else value||'{"reviewed":false}'::jsonb end)
     from jsonb_array_elements(coalesce(next_draft->'openings','[]'))),'[]'::jsonb));
  end if;
  update public.captures set draft=next_draft where id=c.id;
 elsif p_action='reserve' then
  if not private.capture_active_walls(c.draft->>'topology') @> jsonb_build_array(p_payload->>'primaryWallId') then
   raise exception 'invalid-wall';
  end if;
  declared:=(p_payload->>'declaredBytes')::integer;
  if declared not between 1 and 4000000 or (select count(*) from public.capture_photos where capture_id=c.id)>=8 or
    (select input_reserved from private.capture_counters where capture_id=c.id)+declared>32000000 or
    (select count(*) from private.capture_events where owner_id=owner and kind='ingest' and created_at>now()-interval '1 hour')>=32 then raise exception 'quota'; end if;
  photo:=gen_random_uuid();
  update private.capture_counters set input_reserved=input_reserved+declared where capture_id=c.id;
  insert into public.capture_photos(id,capture_id,owner_id,object_key,primary_wall_id,declared_bytes)
   values(photo,c.id,owner,owner::text||'/'||c.id::text||'/'||photo::text||'.jpg',p_payload->>'primaryWallId',declared);
  insert into private.capture_events(owner_id,kind) values(owner,'ingest');
 elsif p_action='associate' then
  active:=private.capture_active_walls(c.draft->>'topology');
  if not active @> jsonb_build_array(p_payload->>'primaryWallId')
     or jsonb_typeof(p_payload->'observedWallIds') is distinct from 'array'
     or jsonb_array_length(p_payload->'observedWallIds')>6
     or not active @> (p_payload->'observedWallIds') then raise exception 'invalid-wall'; end if;
  update public.capture_photos set primary_wall_id=p_payload->>'primaryWallId',observed_wall_ids=p_payload->'observedWallIds',analysis_status='unknown',semantics=null where id=(p_payload->>'photoId')::uuid and capture_id=c.id;
  if not found then raise exception 'not-found'; end if;
 elsif p_action='remove-photo' then
  select id into photo from public.capture_photos where id=(p_payload->>'photoId')::uuid and capture_id=c.id;
  if not found then raise exception 'not-found'; end if;
  insert into private.capture_cleanup_jobs(capture_id,keys,reason) select c.id,jsonb_build_array(object_key),'removed-photo' from public.capture_photos where id=photo;
  delete from public.capture_photos where id=photo;
 else raise exception 'not-found';
 end if;
 if p_action in ('reserve','associate','remove-photo') then
  for evidence in select value from jsonb_array_elements(coalesce(c.draft->'dimensionEvidence','[]')) loop
   if coalesce(evidence->>'overrideReason','')='' and c.draft->(evidence->>'field')=evidence->'valueM' then
    c.draft:=jsonb_set(c.draft,array[evidence->>'field'],'null');
   end if;
  end loop;
  update public.captures set draft=c.draft||'{"dimensionsConfirmed":false,"wallReviews":[],"furnitureAcknowledged":false,"dimensionEvidence":[]}',calibrations='[]' where id=c.id;
 end if;
 perform private.capture_revoke(c.id);
 return private.capture_json(c.id);
end $$;

create or replace function private.capture_authority(p_action text,p_owner uuid,p_capture uuid,p_revision integer,p_lease uuid,p_payload jsonb)
returns jsonb language plpgsql security definer set search_path='' as $$
declare c public.captures; photo public.capture_photos; total integer; proposals jsonb; affected jsonb; reviews jsonb; active jsonb;
begin
 if not exists(select 1 from auth.users u where u.id=p_owner and u.is_anonymous is true) then raise exception 'not-found'; end if;
 perform pg_advisory_xact_lock(hashtextextended(p_owner::text,0));
 select * into c from public.captures where id=p_capture and owner_id=p_owner and state<>'deleting' and expires_at>now() for update;
 if not found then raise exception 'not-found'; end if;
 if c.revision<>p_revision then raise exception 'stale-capture'; end if;
 if not exists(select 1 from private.capture_operations where id=p_lease and owner_id=p_owner and capture_id=c.id and revision=c.revision and expires_at>now()) then raise exception 'lease-expired'; end if;
 if p_action in ('finalize-photo','begin-analysis','semantics','analysis-failed','upload-failed') then
  select * into photo from public.capture_photos where id=(p_payload->>'photoId')::uuid and capture_id=c.id and owner_id=p_owner for update;
  if not found then raise exception 'not-found'; end if;
 end if;
 if p_action='finalize-photo' then
  if photo.state<>'reserved' or (p_payload->>'inputBytes')::integer>photo.declared_bytes then raise exception 'quota'; end if;
  if exists(select 1 from public.capture_photos where capture_id=c.id and sha256=p_payload->>'sha256' and id<>photo.id) then raise exception 'quota'; end if;
  update public.capture_photos set state='accepted',input_bytes=(p_payload->>'inputBytes')::integer,
   canonical_bytes=(p_payload->>'canonicalBytes')::integer,sha256=p_payload->>'sha256',width_px=(p_payload->>'widthPx')::integer,height_px=(p_payload->>'heightPx')::integer where id=photo.id;
 elsif p_action='begin-analysis' then
  select analysis_total into total from private.capture_counters where capture_id=c.id;
  if photo.state<>'accepted' or photo.analysis_attempts>=2 or total>=16 then raise exception 'attempt-limit'; end if;
  update private.capture_counters set analysis_total=analysis_total+1 where capture_id=c.id;
  update public.capture_photos set analysis_attempts=analysis_attempts+1,analysis_status='pending',input_revision=c.revision where id=photo.id;
 elsif p_action='semantics' then
  if photo.state<>'accepted' or photo.analysis_status<>'pending' or photo.sha256<>p_payload->>'sha256' or photo.input_revision<>c.revision then raise exception 'stale-capture'; end if;
  active:=private.capture_active_walls(c.draft->>'topology');
  -- Each bounded proposal set contributes affected walls, including removed evidence.
  -- Read the immutable prior photo row before replacing its stored semantics.
  proposals:=coalesce(photo.semantics->'openings','[]'::jsonb)||coalesce(p_payload->'semantics'->'openings','[]'::jsonb);
  affected:=jsonb_build_array(photo.primary_wall_id)||photo.observed_wall_ids||coalesce(
   (select jsonb_agg(value->'wallId') from jsonb_array_elements(proposals)
    where active @> jsonb_build_array(value->>'wallId')),'[]'::jsonb);
  if exists(select 1 from jsonb_array_elements(proposals) where value->>'wallId' is null or not active @> jsonb_build_array(value->>'wallId')) then
   affected:=active;
  end if;
  update public.capture_photos set analysis_status='complete',semantics=p_payload->'semantics' where id=photo.id;
  select coalesce(jsonb_agg(value),'[]') into reviews from jsonb_array_elements(coalesce(c.draft->'wallReviews','[]'))
   where not affected @> jsonb_build_array(value);
  update public.captures set draft=jsonb_set(c.draft,'{wallReviews}',reviews)||
   case when p_payload->'semantics'->>'detectedFurniture' is distinct from 'absent'
    then '{"furnitureAcknowledged":false}'::jsonb else '{}'::jsonb end where id=c.id;
  perform private.capture_revoke(c.id);
 elsif p_action='analysis-failed' then
  update public.capture_photos set analysis_status='failed' where id=photo.id;
 elsif p_action='upload-failed' then
  update public.capture_photos set state='failed' where id=photo.id;
  insert into private.capture_cleanup_jobs(capture_id,keys,reason) values(c.id,jsonb_build_array(photo.object_key),'failed-upload');
 elsif p_action='confirm' then
  if octet_length(p_payload::text)>131072 then raise exception 'quota'; end if;
  update public.captures set state='confirmed',confirmed_revision=c.revision,room_hash=p_payload->>'roomHash',validated_room=p_payload->'room' where id=c.id;
 elsif p_action='calibration' then
  -- The bounded canonical-photo binding is checked before storing user-authored provenance.
  if octet_length(p_payload::text)>32768 then raise exception 'quota'; end if;
  if jsonb_array_length(c.calibrations)>=16 then raise exception 'quota'; end if;
  update public.captures set calibrations=calibrations||jsonb_build_array(p_payload) where id=c.id;
 else raise exception 'not-found';
 end if;
 return private.capture_json(c.id);
end $$;

commit;
