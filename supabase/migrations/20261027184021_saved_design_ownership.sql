-- Saved copies retain confirmed metadata, never photo bytes or runtime authority.
begin;

-- Deliberately broaden the legacy-named gate to both current owner kinds.
-- Exact signed boolean must agree with the current Auth-owned row.
create or replace function private.capture_anonymous_owner() returns boolean
language sql security definer stable set search_path='' as $$
 select exists(select 1 from auth.users u where u.id=auth.uid()
   and jsonb_typeof(auth.jwt()->'is_anonymous')='boolean'
   and auth.jwt()->'is_anonymous'=to_jsonb(u.is_anonymous))
$$;

create table public.saved_designs (
 id uuid primary key default gen_random_uuid(),
 owner_id uuid not null references auth.users(id),
 idempotency_key text not null check(idempotency_key ~ '^[A-Za-z0-9_-]{8,128}$'),
 request_hash text not null check(request_hash ~ '^[0-9a-f]{64}$'),
 source_session text, source_version integer, policy_version text,
 schema_version integer, catalogue_version text, snapshot jsonb,
 snapshot_sha256 text, fingerprint text,
 created_at timestamptz not null default now(), deleted_at timestamptz, purge_at timestamptz,
 unique(owner_id,idempotency_key),
 check ((deleted_at is null and purge_at is null and source_session is not null
    and source_version>0 and policy_version='saved-until-deleted-v1' and schema_version=1
    and catalogue_version is not null and snapshot is not null
    and snapshot_sha256 ~ '^[0-9a-f]{64}$' and fingerprint ~ '^[0-9a-f]{64}$')
   or (deleted_at is not null and purge_at=deleted_at+interval '25 hours'
    and source_session is null and source_version is null and policy_version is null
    and schema_version is null and catalogue_version is null and snapshot is null
    and snapshot_sha256 is null and fingerprint is null)),
 check(octet_length(snapshot::text)<=524288)
);
create index saved_designs_owner_page on public.saved_designs(owner_id,created_at desc,id desc) where deleted_at is null;
create index saved_designs_owner_rate on public.saved_designs(owner_id,created_at);
create index saved_designs_owner_purge on public.saved_designs(owner_id,purge_at) where deleted_at is not null;
alter table public.saved_designs enable row level security;
revoke all on public.saved_designs from public,anon,authenticated,service_role;
grant select on public.saved_designs to authenticated;
create policy saved_owner_read on public.saved_designs for select to authenticated
 using ((select private.capture_anonymous_owner()) and owner_id=(select auth.uid()) and deleted_at is null);
-- No direct INSERT/UPDATE/DELETE grants or policies: immutable owner/content.

create function private.saved_json(p_id uuid) returns jsonb
language sql stable security invoker set search_path='' as $$
 select case when deleted_at is not null then jsonb_build_object('status','deleted','id',id,'createdAt',created_at)
 else jsonb_build_object('status','active','id',id,'createdAt',created_at,'requestHash',request_hash,
   'snapshot',snapshot,'digest',snapshot_sha256,'fingerprint',fingerprint) end
 from public.saved_designs where id=p_id
$$;

create function public.saved_design_user(p_action text,p_id uuid default null,p_key text default null,p_identity text default null,p_cursor text default null)
returns jsonb language plpgsql security definer set search_path='' as $$
declare owner uuid:=auth.uid(); row public.saved_designs; result jsonb; marker jsonb; page_time timestamptz; page_id uuid; deletion_time timestamptz;
begin
 if owner is null or not private.capture_anonymous_owner() then raise exception 'not-found'; end if;
 perform pg_advisory_xact_lock(hashtextextended(owner::text,0));
 perform 1 from auth.users u where u.id=owner and jsonb_typeof(auth.jwt()->'is_anonymous')='boolean'
  and to_jsonb(u.is_anonymous)=auth.jwt()->'is_anonymous' for share;
 if not found then raise exception 'not-found'; end if;
 if p_action='list' then
  if p_cursor is not null then
   begin
    if length(p_cursor)>256 then raise exception 'invalid cursor'; end if;
    marker:=convert_from(decode(p_cursor,'base64'),'UTF8')::jsonb;
    if jsonb_typeof(marker)<>'array' or jsonb_array_length(marker)<>2 then raise exception 'invalid cursor'; end if;
    page_time:=(marker->>0)::timestamptz; page_id:=(marker->>1)::uuid;
    if page_time is null or page_id is null then raise exception 'invalid cursor'; end if;
   exception when others then raise exception 'invalid-cursor'; end;
  end if;
  select coalesce(jsonb_agg(jsonb_build_object('id',id,'createdAt',created_at,'idempotencyKey',idempotency_key,
    'roomType',snapshot->>'roomType','captureId',snapshot->'capture'->>'id') order by created_at desc,id desc),'[]'::jsonb)
  into result from (select * from public.saved_designs where owner_id=owner and deleted_at is null
    and (p_cursor is null or (created_at,id)<(page_time,page_id)) order by created_at desc,id desc limit 25) page;
  marker:=null;
  if jsonb_array_length(result)=25 then
   marker:=result->24;
   if not exists(select 1 from public.saved_designs where owner_id=owner and deleted_at is null
       and (created_at,id)<((marker->>'createdAt')::timestamptz,(marker->>'id')::uuid)) then marker:=null; end if;
  end if;
  return jsonb_build_object('items',result,'nextCursor',case when marker is null then null else
   replace(encode(convert_to(jsonb_build_array(marker->>'createdAt',marker->>'id')::text,'UTF8'),'base64'),E'\n','') end);
 elsif p_action='replay' then
  select * into row from public.saved_designs where owner_id=owner and idempotency_key=p_key;
  if not found then return '{"status":"missing"}'::jsonb; end if;
  if row.request_hash is distinct from p_identity then raise exception 'idempotency-conflict'; end if;
  return private.saved_json(row.id);
 elsif p_action in ('read','delete') then
  select * into row from public.saved_designs where id=p_id and owner_id=owner for update;
  if p_action='delete' then
   if found and row.deleted_at is null then
    deletion_time:=clock_timestamp();
    update public.saved_designs set snapshot=null,snapshot_sha256=null,fingerprint=null,
     source_session=null,source_version=null,policy_version=null,schema_version=null,catalogue_version=null,
     deleted_at=deletion_time,purge_at=deletion_time+interval '25 hours' where id=row.id and owner_id=owner;
   end if;
   return '{}'::jsonb;
  end if;
  if not found then raise exception 'not-found'; end if;
  return private.saved_json(row.id);
 end if;
 raise exception 'not-found';
end $$;

create function public.saved_design_commit(p_owner uuid,p_anonymous boolean,p_key text,p_identity text,
 p_session text,p_version integer,p_canonical text,p_digest text,p_source jsonb)
returns jsonb language plpgsql security definer set search_path='' as $$
declare row public.saved_designs; c public.captures; document jsonb; digest text; fingerprint text;
begin
 -- Narrow service-only creation; FastAPI supplies the verified principal and server snapshot.
 -- Owner lock always precedes auth/source row locks, matching Capture mutations/deletion.
 perform pg_advisory_xact_lock(hashtextextended(p_owner::text,0));
 perform 1 from auth.users where id=p_owner and is_anonymous=p_anonymous for share;
 if not found then raise exception 'not-found'; end if;
 select * into row from public.saved_designs where owner_id=p_owner and idempotency_key=p_key for update;
 if found then
  if row.request_hash is distinct from p_identity then raise exception 'idempotency-conflict'; end if;
  return private.saved_json(row.id);
 end if;
 if p_source->>'kind'='capture' then
  select * into c from public.captures where id=(p_source->>'captureId')::uuid and owner_id=p_owner for update;
  if not found or c.state<>'confirmed' or c.expires_at<=clock_timestamp()
   or c.confirmed_revision is distinct from (p_source->>'revision')::integer
   or c.revision is distinct from (p_source->>'revision')::integer
   or c.room_hash is distinct from p_source->>'roomHash' then raise exception 'not-found'; end if;
  if not exists(select 1 from private.capture_operations where id=(p_source->>'lease')::uuid
   and capture_id=c.id and owner_id=p_owner and revision=c.revision and kind='session' and expires_at>clock_timestamp()) then raise exception 'lease-expired'; end if;
 elsif p_source->>'kind'='saved' then
  select * into row from public.saved_designs where id=(p_source->>'id')::uuid and owner_id=p_owner for update;
  if not found or row.deleted_at is not null or row.snapshot_sha256 is distinct from p_source->>'digest' then raise exception 'not-found'; end if;
 elsif p_source->>'kind' is distinct from 'fixture' then raise exception 'not-found'; end if;
 if p_source->>'sessionExpiresAt' is null or
  to_timestamp((p_source->>'sessionExpiresAt')::double precision)<=clock_timestamp() then raise exception 'lease-expired'; end if;
 if p_canonical is null or octet_length(p_canonical)>262144 or p_version<1
   or length(p_session) not between 1 and 128 or p_identity !~ '^[0-9a-f]{64}$' then raise exception 'quota'; end if;
 document:=p_canonical::jsonb;
 digest:=encode(sha256(convert_to(p_canonical,'UTF8')),'hex');
 if digest is distinct from p_digest or document->>'schemaVersion'<>'1' or document->>'status'<>'solved'
   or document->>'catalogueVersion' is null then raise exception 'corrupt-snapshot'; end if;
 if p_source->>'kind'='capture' and (document->'capture'->>'id' is distinct from c.id::text
   or document->'capture'->>'roomHash' is distinct from c.room_hash
   or document->'room' is distinct from c.validated_room
   or document->>'roomType' is distinct from c.draft->>'roomType') then raise exception 'not-found'; end if;
 delete from public.saved_designs where owner_id=p_owner and deleted_at is not null and purge_at<=clock_timestamp();
 if (select count(*) from public.saved_designs where owner_id=p_owner and deleted_at is null)>=100
   or (select count(*) from public.saved_designs where owner_id=p_owner and created_at>clock_timestamp()-interval '1 hour')>=100
   or (select count(*) from public.saved_designs where owner_id=p_owner)>=3100 then raise exception 'quota'; end if;
 fingerprint:=encode(sha256(convert_to(p_identity||':'||digest||':1:'||(document->>'catalogueVersion'),'UTF8')),'hex');
 -- Recheck actual liveness in the insertion statement, after every lock wait,
 -- normalization/quota operation and immediately before publishing new content.
 insert into public.saved_designs(owner_id,idempotency_key,request_hash,source_session,source_version,policy_version,
  schema_version,catalogue_version,snapshot,snapshot_sha256,fingerprint,created_at)
 select p_owner,p_key,p_identity,p_session,p_version,'saved-until-deleted-v1',1,document->>'catalogueVersion',document,digest,fingerprint,clock_timestamp()
 where to_timestamp((p_source->>'sessionExpiresAt')::double precision)>clock_timestamp()
  and (p_source->>'kind'<>'capture' or (c.expires_at>clock_timestamp() and exists(
   select 1 from private.capture_operations where id=(p_source->>'lease')::uuid
   and capture_id=c.id and owner_id=p_owner and revision=c.revision and kind='session' and expires_at>clock_timestamp())))
 returning * into row;
 if not found then raise exception 'lease-expired'; end if;
 return private.saved_json(row.id);
end $$;

revoke all on function private.saved_json(uuid) from public,anon,authenticated,service_role;
revoke all on function public.saved_design_user(text,uuid,text,text,text),
 public.saved_design_commit(uuid,boolean,text,text,text,integer,text,text,jsonb) from public,anon,authenticated,service_role;
grant execute on function public.saved_design_user(text,uuid,text,text,text) to authenticated;
grant execute on function public.saved_design_commit(uuid,boolean,text,text,text,integer,text,text,jsonb) to service_role;

-- Capture authority's existing service-only body is replaced below with a
-- current principal kind check. Storage's restrictive SELECT denial is untouched.

create or replace function private.capture_user(p_action text,p_capture uuid,p_revision integer,p_payload jsonb) returns jsonb
language plpgsql security definer set search_path='' as $$
declare owner uuid:=auth.uid(); c public.captures; photo uuid; lease_id uuid; lease_seconds integer; v_kind text; declared integer; evidence jsonb; next_draft jsonb; active jsonb; field text; topology_changed boolean; dimensions_changed boolean;
begin
 if owner is null or not private.capture_anonymous_owner() then raise exception 'not-found'; end if;
 if octet_length(p_payload::text)>32768 then raise exception 'quota'; end if;
 perform pg_advisory_xact_lock(hashtextextended(owner::text,0));
 perform 1 from auth.users u where u.id=owner and jsonb_typeof(auth.jwt()->'is_anonymous')='boolean'
  and to_jsonb(u.is_anonymous)=auth.jwt()->'is_anonymous' for share;
 if not found then raise exception 'not-found'; end if;
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
 perform pg_advisory_xact_lock(hashtextextended(p_owner::text,0));
 perform 1 from auth.users u where u.id=p_owner
  and jsonb_typeof(p_payload->'principalIsAnonymous')='boolean'
  and to_jsonb(u.is_anonymous)=p_payload->'principalIsAnonymous' for share;
 if not found then raise exception 'not-found'; end if;
 p_payload:=p_payload-'principalIsAnonymous';
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
