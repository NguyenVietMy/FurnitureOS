-- Disposable LOCAL PostgreSQL contract fixture, never a Supabase migration or live proof.
do $$begin
 if not exists(select 1 from pg_roles where rolname='anon') then create role anon nologin; end if;
 if not exists(select 1 from pg_roles where rolname='authenticated') then create role authenticated nologin; end if;
 if not exists(select 1 from pg_roles where rolname='service_role') then create role service_role nologin bypassrls; end if;
end $$;
create schema auth;
create table auth.users(id uuid primary key,is_anonymous boolean not null default false);
create function auth.uid() returns uuid language sql stable as $$
 select nullif(current_setting('request.jwt.claim.sub',true),'')::uuid
$$;
-- Explicit local signed-claim fixture; real Supabase supplies validated JWT claims.
create function auth.jwt() returns jsonb language sql stable as $$
 select coalesce(nullif(current_setting('request.jwt.claims',true),'')::jsonb,'{}'::jsonb)
$$;
grant usage on schema auth to anon,authenticated,service_role;
grant execute on function auth.uid(),auth.jwt() to anon,authenticated,service_role;
create schema storage;
create table storage.buckets(id text primary key,name text,public boolean,file_size_limit bigint,allowed_mime_types text[]);
create table storage.objects(id uuid default gen_random_uuid(),bucket_id text,name text,owner_id text,created_at timestamptz default now());
alter table storage.objects enable row level security;
grant usage on schema storage to authenticated,service_role;
grant select on storage.objects to authenticated;
grant select on storage.objects to service_role;
create function storage.foldername(name text) returns text[] language sql immutable as $$
 select (string_to_array(name,'/'))[1:array_length(string_to_array(name,'/'),1)-1]
$$;
create function storage.allow_only_operation(operation text) returns boolean language sql stable as $$
 -- Explicit fixture GUC, with the same prefix normalization as the deployed helper.
 select coalesce(regexp_replace(current_setting('test.storage.operation',true),'^storage[.]','')=
  regexp_replace(operation,'^storage[.]','') and operation<>'',false)
$$;
