-- Capture v1: no direct private-data mutation or client Storage ingestion.
create schema if not exists private;
revoke all on schema private from public;
grant usage on schema private to authenticated, service_role;

create table public.captures (
 id uuid primary key default gen_random_uuid(), owner_id uuid not null references auth.users(id),
 created_at timestamptz not null default now(), expires_at timestamptz not null default now()+interval '24 hours',
 revision integer not null default 1 check(revision>0), state text not null default 'draft' check(state in ('draft','confirmed','deleting')),
 draft jsonb not null default '{"roomType":"","topology":""}', confirmed_revision integer, room_hash text, validated_room jsonb,
 cleanup_status text not null default 'none', policy_version text not null default 'capture-24h-v1',
 calibrations jsonb not null default '[]' check(jsonb_array_length(calibrations)<=16 and octet_length(calibrations::text)<=32768),
 unique(id,owner_id), check(expires_at=created_at+interval '24 hours'),
 check(octet_length(draft::text)<=32768), check(octet_length(coalesce(validated_room,'{}')::text)<=131072)
);
create table public.capture_photos (
 id uuid primary key, capture_id uuid not null, owner_id uuid not null,
 object_key text not null unique, primary_wall_id text not null check(primary_wall_id in ('wall-north','wall-east','wall-south','wall-west')),
 observed_wall_ids jsonb not null default '[]', state text not null default 'reserved' check(state in ('reserved','accepted','unavailable','failed')),
 declared_bytes integer not null check(declared_bytes between 1 and 4000000), input_bytes integer not null default 0 check(input_bytes between 0 and 4000000),
 canonical_bytes integer not null default 0 check(canonical_bytes between 0 and 400000), sha256 text,
 width_px integer not null default 0, height_px integer not null default 0,
 analysis_status text not null default 'pending' check(analysis_status in ('pending','complete','failed','unknown')),
 analysis_attempts integer not null default 0 check(analysis_attempts between 0 and 2), semantics jsonb,
 created_at timestamptz not null default now(), input_revision integer,
 foreign key(capture_id,owner_id) references public.captures(id,owner_id),
 check(jsonb_array_length(observed_wall_ids)<=4),check(octet_length(coalesce(semantics,'{}')::text)<=32768),
 check(object_key=owner_id::text||'/'||capture_id::text||'/'||id::text||'.jpg')
);
create index captures_owner_active on public.captures(owner_id,expires_at);
create index capture_photos_parent on public.capture_photos(capture_id);
create table private.capture_operations (
 id uuid primary key default gen_random_uuid(), owner_id uuid not null, capture_id uuid not null,
 revision integer not null, kind text not null, expires_at timestamptz not null, photo_id uuid,
 created_at timestamptz not null default now()
);
create index capture_operations_owner on private.capture_operations(owner_id,expires_at);
create table private.capture_events (owner_id uuid not null, kind text not null, created_at timestamptz not null default now());
create index capture_events_owner on private.capture_events(owner_id,kind,created_at);
create table private.capture_counters (
 capture_id uuid primary key references public.captures(id), input_reserved bigint not null default 0 check(input_reserved between 0 and 32000000),
 analysis_total integer not null default 0 check(analysis_total between 0 and 16)
);
create table private.capture_cleanup_jobs (
 id uuid primary key default gen_random_uuid(), capture_id uuid, keys jsonb not null, removed jsonb not null default '[]',
 reason text not null, status text not null default 'pending', attempts integer not null default 0,
 next_attempt timestamptz not null default now(), lease_token uuid, lease_until timestamptz,
 created_at timestamptz not null default now(), last_error text,
 attention_fingerprint text unique check(attention_fingerprint is null or attention_fingerprint ~ '^[0-9a-f]{64}$'),
 attention_path text check(attention_path is null or octet_length(attention_path)<=1024),
 check(jsonb_array_length(keys)<=100),check(jsonb_array_length(removed)<=100)
);
create index capture_cleanup_due on private.capture_cleanup_jobs(next_attempt,status);
create table private.capture_worker_state (id boolean primary key default true check(id), cursor text not null default '', last_scheduled_run timestamptz, previous_revoked boolean not null default true);

alter table public.captures enable row level security;
alter table public.capture_photos enable row level security;
alter table private.capture_operations enable row level security;
alter table private.capture_events enable row level security;
alter table private.capture_counters enable row level security;
alter table private.capture_cleanup_jobs enable row level security;
alter table private.capture_worker_state enable row level security;
revoke all on public.captures,public.capture_photos from anon,authenticated;
grant select on public.captures,public.capture_photos to authenticated;
revoke all on all tables in schema private from anon,authenticated;
-- Signed platform claim plus current Auth-owned row; mutable metadata is never identity.
create function private.capture_anonymous_owner() returns boolean
language sql security definer stable set search_path='' as $$
 select coalesce(auth.jwt()->'is_anonymous'='true'::jsonb,false) and
  exists(select 1 from auth.users u where u.id=auth.uid() and u.is_anonymous is true)
$$;
create policy capture_owner_read on public.captures for select to authenticated using
 ((select private.capture_anonymous_owner()) and owner_id=(select auth.uid()) and state<>'deleting' and expires_at>now());
create policy capture_photo_owner_read on public.capture_photos for select to authenticated using
 ((select private.capture_anonymous_owner()) and owner_id=(select auth.uid()) and exists(select 1 from public.captures c where c.id=capture_id and c.owner_id=capture_photos.owner_id and c.state<>'deleting' and c.expires_at>now()));

-- Snapshot is only reachable through scoped owner or authority operations.
create function private.capture_json(p_id uuid) returns jsonb language sql stable set search_path='' as $$
 select jsonb_build_object('id',c.id,'revision',c.revision,'state',c.state,'createdAt',c.created_at,'expiresAt',c.expires_at,
  'draft',case when c.state='deleting' then '{}'::jsonb else c.draft end,
  'confirmedRevision',case when c.state='deleting' then null else c.confirmed_revision end,
  'roomHash',case when c.state='deleting' then null else c.room_hash end,
  'room',case when c.state='deleting' then null else c.validated_room end,'cleanupStatus',c.cleanup_status,
  'calibrations',case when c.state='deleting' then '[]'::jsonb else c.calibrations end,
  'photos',case when c.state='deleting' then '[]'::jsonb else coalesce((select jsonb_agg(jsonb_build_object(
   'id',p.id,'primaryWallId',p.primary_wall_id,'observedWallIds',p.observed_wall_ids,'state',p.state,
   'declaredBytes',p.declared_bytes,'inputBytes',p.input_bytes,'canonicalBytes',p.canonical_bytes,'sha256',p.sha256,
   'widthPx',p.width_px,'heightPx',p.height_px,'analysisStatus',p.analysis_status,'analysisAttempts',p.analysis_attempts,
   'semantics',p.semantics) order by p.created_at,p.id) from public.capture_photos p where p.capture_id=c.id),'[]'::jsonb) end)
 from public.captures c where c.id=p_id and (c.state='deleting' or c.expires_at>now())
$$;
create function private.capture_deletion_json(p_id uuid) returns jsonb language sql stable set search_path='' as $$
 select jsonb_build_object('id',c.id,'state','deleting','inaccessible',true,'cleanupStatus',c.cleanup_status)
 from public.captures c where c.id=p_id and c.state='deleting'
$$;
create function private.capture_revoke(p_id uuid) returns void language plpgsql set search_path='' as $$
begin
 update public.captures set revision=revision+1,state='draft',confirmed_revision=null,room_hash=null,validated_room=null where id=p_id;
end $$;
create function private.capture_enqueue(p_id uuid,p_reason text) returns void language plpgsql set search_path='' as $$
declare inventory jsonb;
begin
 select coalesce(jsonb_agg(object_key),'[]') into inventory from public.capture_photos where capture_id=p_id;
 update public.captures set state='deleting',revision=revision+1,confirmed_revision=null,room_hash=null,validated_room=null,cleanup_status='pending' where id=p_id and state<>'deleting';
 delete from private.capture_operations where capture_id=p_id;
 if not exists(select 1 from private.capture_cleanup_jobs where capture_id=p_id and reason in ('manual','expiry')) then
  insert into private.capture_cleanup_jobs(capture_id,keys,reason) values(p_id,inventory,p_reason);
 end if;
end $$;

create function private.capture_user(p_action text,p_capture uuid,p_revision integer,p_payload jsonb) returns jsonb
language plpgsql security definer set search_path='' as $$
declare owner uuid:=auth.uid(); c public.captures; photo uuid; lease_id uuid; lease_seconds integer; v_kind text; declared integer; evidence jsonb;
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
  update public.captures set draft=p_payload->'draft' where id=c.id;
 elsif p_action='reserve' then
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
create function public.capture_user_operation(p_action text,p_capture uuid default null,p_revision integer default null,p_payload jsonb default '{}')
returns jsonb language sql security invoker set search_path='' as $$
 select private.capture_user(p_action,p_capture,p_revision,p_payload)
$$;

create function private.capture_authority(p_action text,p_owner uuid,p_capture uuid,p_revision integer,p_lease uuid,p_payload jsonb)
returns jsonb language plpgsql security definer set search_path='' as $$
declare c public.captures; photo public.capture_photos; total integer; proposals jsonb; affected jsonb; reviews jsonb;
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
  -- Each bounded proposal set contributes affected walls, including removed evidence.
  -- Read the immutable prior photo row before replacing its stored semantics.
  proposals:=coalesce(photo.semantics->'openings','[]'::jsonb)||coalesce(p_payload->'semantics'->'openings','[]'::jsonb);
  affected:=jsonb_build_array(photo.primary_wall_id)||photo.observed_wall_ids||coalesce(
   (select jsonb_agg(value->'wallId') from jsonb_array_elements(proposals)
    where value->>'wallId' in ('wall-north','wall-east','wall-south','wall-west')),'[]'::jsonb);
  if exists(select 1 from jsonb_array_elements(proposals) where value->>'wallId' is null) then
   affected:='["wall-north","wall-east","wall-south","wall-west"]';
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
create function public.capture_authority(p_action text,p_owner uuid,p_capture uuid,p_revision integer,p_lease uuid,p_payload jsonb default '{}')
returns jsonb language sql security invoker set search_path='' as $$
 select private.capture_authority(p_action,p_owner,p_capture,p_revision,p_lease,p_payload)
$$;
-- Service-only cleanup: persistent claims/progress, not SQL object deletion.
create function private.capture_cleanup(p_action text,p_payload jsonb) returns jsonb
language plpgsql security definer set search_path='' as $$
declare job private.capture_cleanup_jobs; jobs jsonb; target uuid; row_key text;
begin
 if p_action='claim' then
  for target in select id from public.captures where expires_at<=now() and state<>'deleting' order by expires_at limit 10 for update skip locked loop
   perform private.capture_enqueue(target,'expiry');
  end loop;
  -- Stalled reservation keys remain durable through the grace period.
  for row_key,target in select p.object_key,p.id from public.capture_photos p where p.state='reserved' and p.created_at<now()-interval '12 minutes' and
    not exists(select 1 from private.capture_operations o where o.capture_id=p.capture_id and o.expires_at>now()) limit 100 loop
   if not exists(select 1 from private.capture_cleanup_jobs where keys @> jsonb_build_array(row_key)) then
    insert into private.capture_cleanup_jobs(keys,reason) values(jsonb_build_array(row_key),'stalled-reservation');
   end if;
   update public.capture_photos set state='failed' where id=target;
  end loop;
  delete from private.capture_events where created_at<now()-interval '24 hours';
  delete from private.capture_operations where expires_at<now()-interval '10 minutes';
  with due as (select id from private.capture_cleanup_jobs where next_attempt<=now() and (lease_until is null or lease_until<=now()) order by next_attempt,id limit 10 for update skip locked),
  claimed as (update private.capture_cleanup_jobs j set lease_token=gen_random_uuid(),lease_until=now()+interval '120 seconds',status='working' from due where j.id=due.id returning j.*)
  select coalesce(jsonb_agg(to_jsonb(claimed)),'[]') into jobs from claimed;
  return jobs;
 elsif p_action='scheduled' then
  insert into private.capture_worker_state(id,last_scheduled_run,previous_revoked) values(true,now(),true) on conflict(id) do update set last_scheduled_run=now(),previous_revoked=true;
  return '{}';
 elsif p_action='rotate' then
  insert into private.capture_worker_state(id,previous_revoked) values(true,false) on conflict(id) do update set previous_revoked=false;
  return '{}';
 elsif p_action='audit-page' then
  -- Bound reconciliation of accepted manifests whose actual Storage metadata disappeared.
  -- Active operations hold a lease and are excluded until a subsequent pass.
  for row_key,target in select p.object_key,p.capture_id from public.capture_photos p
    join public.captures c on c.id=p.capture_id where p.state='accepted' and c.state<>'deleting'
    and not exists(select 1 from storage.objects o where o.bucket_id='captures' and o.name=p.object_key)
    and not exists(select 1 from private.capture_operations l where l.capture_id=p.capture_id and l.expires_at>now()) limit 100 loop
   update public.capture_photos set state='unavailable' where object_key=row_key;
   perform private.capture_revoke(target);
  end loop;
  select cursor into row_key from private.capture_worker_state where id=true;
  select coalesce(jsonb_agg(jsonb_build_object('name',name,'created_at',created_at) order by name),'[]') into jobs from
    (select name,created_at from storage.objects where bucket_id='captures' and name>coalesce(row_key,'') order by name limit 100) page;
  return jsonb_build_object('objects',jobs,'cursor',case when jsonb_array_length(jobs)<100 then '' else jobs->-1->>'name' end);
 elsif p_action='audit' then
  -- Caller supplies only a bounded Storage metadata page, never a SQL byte deletion.
  if jsonb_array_length(p_payload->'objects')>100 then raise exception 'quota'; end if;
  for row_key in select value->>'name' from jsonb_array_elements(p_payload->'objects') loop
   if row_key !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.jpg$' then
    insert into private.capture_cleanup_jobs(keys,reason,status,next_attempt,last_error,attention_fingerprint,attention_path)
     values('[]','unrecognized-path','attention-required',now()+interval '24 hours','unrecognized-path',
       encode(sha256(convert_to(row_key,'UTF8')),'hex'),case when octet_length(row_key)<=1024 then row_key else null end)
     on conflict(attention_fingerprint) do nothing;
   elsif not exists(select 1 from public.capture_photos where object_key=row_key) and
    not exists(select 1 from private.capture_operations where capture_id=split_part(row_key,'/',2)::uuid and expires_at>now()) and
    (select (value->>'created_at')::timestamptz<now()-interval '24 hours' from jsonb_array_elements(p_payload->'objects') where value->>'name'=row_key limit 1) then
    if not exists(select 1 from private.capture_cleanup_jobs where keys @> jsonb_build_array(row_key)) then
     insert into private.capture_cleanup_jobs(keys,reason) values(jsonb_build_array(row_key),'orphan');
    end if;
   end if;
  end loop;
  insert into private.capture_worker_state(id,cursor) values(true,p_payload->>'cursor') on conflict(id) do update set cursor=excluded.cursor;
  return '{}';
 elsif p_action='missing-object' then
  select capture_id into target from public.capture_photos where object_key=p_payload->>'key';
  if target is not null then
   update public.capture_photos set state='unavailable' where object_key=p_payload->>'key';
   perform private.capture_revoke(target);
  end if;
  return '{}';
 end if;
 select * into job from private.capture_cleanup_jobs where id=(p_payload->>'id')::uuid and lease_token=(p_payload->>'lease')::uuid and lease_until>now() for update;
 if not found then raise exception 'lease-expired'; end if;
 if p_action='progress' then
  if not job.keys @> jsonb_build_array(p_payload->>'key') then raise exception 'not-found'; end if;
  if not job.removed @> jsonb_build_array(p_payload->>'key') then
   update private.capture_cleanup_jobs set removed=removed||jsonb_build_array(p_payload->>'key') where id=job.id;
  end if;
 elsif p_action='finish' then
  if not job.removed @> job.keys then raise exception 'busy'; end if;
  if job.capture_id is not null and job.reason in ('manual','expiry') then
   if exists(select 1 from private.capture_cleanup_jobs where capture_id=job.capture_id and id<>job.id) then raise exception 'busy'; end if;
   delete from public.capture_photos where capture_id=job.capture_id;
   delete from private.capture_counters where capture_id=job.capture_id;
   delete from public.captures where id=job.capture_id and state='deleting';
  end if;
  delete from private.capture_cleanup_jobs where id=job.id;
 elsif p_action='fail' then
  update private.capture_cleanup_jobs set attempts=least(attempts+1,8),status=case when reason='unrecognized-path' or attempts+1>=8 then 'attention-required' else 'pending' end,
   next_attempt=now()+make_interval(secs=>case when reason='unrecognized-path' or attempts+1>=8 then 86400 else least(900*power(2,attempts)::integer,86400) end),
   lease_until=null,lease_token=null,last_error='storage-unavailable' where id=job.id;
  if job.capture_id is not null then update public.captures set cleanup_status='pending' where id=job.capture_id; end if;
 elsif p_action='yield' then
  update private.capture_cleanup_jobs set lease_until=null,lease_token=null,status='pending' where id=job.id;
 else raise exception 'not-found';
 end if;
 return '{}';
end $$;
create function public.capture_cleanup(p_action text,p_payload jsonb default '{}') returns jsonb language sql security invoker set search_path='' as $$
 select private.capture_cleanup(p_action,p_payload)
$$;
-- One nonpersonal public rotation flag; no owner, object, draft or secret is exposed.
create function public.capture_cleanup_rotation_status() returns boolean language sql security definer stable set search_path='' as $$
 select coalesce((select previous_revoked from private.capture_worker_state where id=true),true)
$$;
revoke execute on function public.capture_cleanup_rotation_status() from public;
grant execute on function public.capture_cleanup_rotation_status() to anon,authenticated,service_role;

revoke execute on all functions in schema private from public,anon,authenticated;
revoke execute on function public.capture_user_operation(text,uuid,integer,jsonb),public.capture_authority(text,uuid,uuid,integer,uuid,jsonb),public.capture_cleanup(text,jsonb) from public,anon,authenticated;
grant execute on function private.capture_user(text,uuid,integer,jsonb),public.capture_user_operation(text,uuid,integer,jsonb) to authenticated;
grant execute on function private.capture_anonymous_owner() to authenticated;
grant execute on function private.capture_authority(text,uuid,uuid,integer,uuid,jsonb),public.capture_authority(text,uuid,uuid,integer,uuid,jsonb),private.capture_cleanup(text,jsonb),public.capture_cleanup(text,jsonb) to service_role;

insert into storage.buckets(id,name,public,file_size_limit,allowed_mime_types)
 values('captures','captures',false,400000,array['image/jpeg']);
create policy capture_private_download on storage.objects for select to authenticated using
 ((select private.capture_anonymous_owner()) and bucket_id='captures' and
 storage.allow_only_operation('object.get_authenticated') and
 (storage.foldername(name))[1]=(select auth.uid()::text) and
 exists(select 1 from public.capture_photos p join public.captures c on c.id=p.capture_id and c.owner_id=p.owner_id
  where p.object_key=name and p.owner_id=(select auth.uid()) and p.state='accepted' and c.state<>'deleting' and c.expires_at>now()));
