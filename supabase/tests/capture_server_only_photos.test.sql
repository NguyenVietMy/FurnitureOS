-- Actual PostgreSQL RLS, with simulated JWT/operation context, not hosted CDN proof.
begin;
insert into storage.objects(bucket_id,name) values ('captures','retained-private.jpg'),('other','other-bucket.jpg');
-- A competing permissive SELECT must not reopen the Capture bucket. Grants
-- deliberately exercise RLS rather than hiding a missing-grant failure.
grant usage on schema storage to anon;
grant select on storage.objects to anon;
create policy test_competing_select on storage.objects for select to anon,authenticated using (true);
set local role authenticated;
do $$declare principal text; phase text; claims text;begin
 foreach principal in array array['11111111-1111-1111-1111-111111111111','22222222-2222-2222-2222-222222222222'] loop
  perform set_config('request.jwt.claim.sub',principal,true);
  foreach claims in array array['{"is_anonymous":true}','{"is_anonymous":false}','{}'] loop
   perform set_config('request.jwt.claims',claims,true);
   foreach phase in array array['object.get_authenticated_info','storage.object.get_authenticated','object.get_info','object.get',
       'object.list','object.sign','object.upload','object.update','object.delete','unknown',''] loop
    perform set_config('test.storage.operation',phase,true);
    if exists(select 1 from storage.objects where bucket_id='captures') then raise exception 'competing policy exposed private bytes'; end if;
    if (select count(*) from storage.objects where bucket_id='other')<>1 then raise exception 'other bucket policy changed'; end if;
   end loop;
  end loop;
 end loop;
end $$;
reset role;
set local role anon;
do $$begin
 if exists(select 1 from storage.objects where bucket_id='captures') then raise exception 'publishable bytes exposed'; end if;
 if (select count(*) from storage.objects where bucket_id='other')<>1 then raise exception 'anon other bucket policy changed'; end if;
end $$;
reset role;
set local role service_role;
do $$begin if (select count(*) from storage.objects)<>2 then raise exception 'trusted byte/cleanup transport blocked'; end if; end $$;
reset role;
do $$begin if (select count(*) from storage.objects)<>2 then raise exception 'objects modified by policy proof'; end if; end $$;
rollback;
