-- Actual PostgreSQL RLS contract with explicitly LOCAL Auth/Storage context stubs.
-- The final server-only policy denies both historical phases. GUCs are simulated.
begin;
insert into auth.users(id,is_anonymous) values
 ('11111111-1111-1111-1111-111111111111',true),('22222222-2222-2222-2222-222222222222',true);
insert into public.captures(id,owner_id) values('33333333-3333-3333-3333-333333333333','11111111-1111-1111-1111-111111111111');
insert into public.capture_photos(id,capture_id,owner_id,object_key,primary_wall_id,state,declared_bytes,sha256)
 values('44444444-4444-4444-4444-444444444444','33333333-3333-3333-3333-333333333333','11111111-1111-1111-1111-111111111111',
 '11111111-1111-1111-1111-111111111111/33333333-3333-3333-3333-333333333333/44444444-4444-4444-4444-444444444444.jpg','wall-north','accepted',1000,repeat('a',64));
insert into storage.objects(bucket_id,name) values
 ('captures','11111111-1111-1111-1111-111111111111/33333333-3333-3333-3333-333333333333/44444444-4444-4444-4444-444444444444.jpg'),
 ('captures','11111111-1111-1111-1111-111111111111/33333333-3333-3333-3333-333333333333/55555555-5555-5555-5555-555555555555.jpg'),
 ('other','11111111-1111-1111-1111-111111111111/33333333-3333-3333-3333-333333333333/44444444-4444-4444-4444-444444444444.jpg');
-- Model platform Storage DML grants so denial exercises RLS, not missing privileges.
grant insert,update,delete on storage.objects to authenticated;
select set_config('request.jwt.claim.sub','11111111-1111-1111-1111-111111111111',true),
 set_config('request.jwt.claims','{"is_anonymous":true}',true);
set local role authenticated;
do $$declare phase text; operation text; affected integer;begin
 if exists(select 1 from storage.objects) then raise exception 'unset operation admitted'; end if;
 -- Neither historical read phase grants direct owner byte access anymore.
 foreach phase in array array['object.get_authenticated_info','storage.object.get_authenticated'] loop
  perform set_config('test.storage.operation',phase,true);
  if exists(select 1 from storage.objects) then raise exception 'direct owner read admitted at %',phase; end if;
 end loop;
 foreach phase in array array['storage.object.get_authenticated_info','object.get_authenticated'] loop
  perform set_config('test.storage.operation',phase,true);
  if exists(select 1 from storage.objects) then raise exception 'normalized phase admitted at %',phase; end if;
 end loop;
 foreach operation in array array['object.list','storage.object.list_v2','object.sign','storage.object.sign_many',
  'object.upload','storage.object.upload_update','object.update','object.delete','storage.object.delete_many',
  'object.get_signed','object.info_public','object.head_authenticated_info','object','unknown',''] loop
  perform set_config('test.storage.operation',operation,true);
  if exists(select 1 from storage.objects) then raise exception 'unsupported operation admitted: %',operation; end if;
 end loop;
 -- Even spoofing an allowed SELECT phase cannot grant INSERT/UPDATE/DELETE policies.
 perform set_config('test.storage.operation','object.get_authenticated_info',true);
 begin insert into storage.objects(bucket_id,name) values('captures','valid-new-key.jpg'); raise exception 'Storage INSERT allowed';
 exception when insufficient_privilege then null; end;
 update storage.objects set name='changed.jpg'; get diagnostics affected=row_count;
 if affected<>0 then raise exception 'Storage UPDATE allowed'; end if;
 delete from storage.objects; get diagnostics affected=row_count;
 if affected<>0 then raise exception 'Storage DELETE allowed'; end if;
 if exists(select 1 from storage.objects) then raise exception 'no-op mutation exposed object'; end if;
 -- Valid signed but foreign principal cannot read either phase.
 perform set_config('request.jwt.claim.sub','22222222-2222-2222-2222-222222222222',true);
 foreach phase in array array['object.get_authenticated_info','object.get_authenticated'] loop
  perform set_config('test.storage.operation',phase,true);
  if exists(select 1 from storage.objects) then raise exception 'cross-owner phase admitted: %',phase; end if;
 end loop;
 perform set_config('request.jwt.claim.sub','11111111-1111-1111-1111-111111111111',true);
 foreach phase in array array['object.get_authenticated_info','object.get_authenticated'] loop
  perform set_config('test.storage.operation',phase,true);
  perform set_config('request.jwt.claims','{"is_anonymous":false,"user_metadata":{"is_anonymous":true}}',true);
  if exists(select 1 from storage.objects) then raise exception 'nonanonymous claim admitted: %',phase; end if;
  perform set_config('request.jwt.claims','{}',true);
  if exists(select 1 from storage.objects) then raise exception 'missing anonymous claim admitted: %',phase; end if;
 end loop;
end $$;
reset role;
select set_config('request.jwt.claims','{"is_anonymous":true}',true);
-- Current trusted identity must also remain anonymous despite an old signed token.
update auth.users set is_anonymous=false where id='11111111-1111-1111-1111-111111111111';
set local role authenticated;
do $$declare phase text;begin
 foreach phase in array array['object.get_authenticated_info','object.get_authenticated'] loop
  perform set_config('test.storage.operation',phase,true);
  if exists(select 1 from storage.objects) then raise exception 'current permanent account admitted: %',phase; end if;
 end loop;
end $$;
reset role;
update auth.users set is_anonymous=true;
-- Manifest acceptance and Capture lifecycle remain required for BOTH phases.
do $$declare phase text;begin
 foreach phase in array array['object.get_authenticated_info','object.get_authenticated'] loop
  perform set_config('test.storage.operation',phase,true);
  update public.capture_photos set state='reserved';
  execute 'set local role authenticated';
  if exists(select 1 from storage.objects) then raise exception 'unaccepted manifest admitted'; end if;
  execute 'reset role';
  update public.capture_photos set state='accepted';
  update public.captures set state='deleting';
  execute 'set local role authenticated';
  if exists(select 1 from storage.objects) then raise exception 'tombstone admitted'; end if;
  execute 'reset role';
  update public.captures set state='draft',created_at=now()-interval '25 hours',expires_at=now()-interval '1 hour';
  execute 'set local role authenticated';
  if exists(select 1 from storage.objects) then raise exception 'expired Capture admitted'; end if;
  execute 'reset role';
  update public.captures set created_at=now(),expires_at=now()+interval '24 hours';
 end loop;
end $$;
set local role anon;
do $$begin
 begin perform count(*) from storage.objects; raise exception 'publishable-key-only SELECT granted';
 exception when insufficient_privilege then null; end;
end $$;
reset role;
do $$begin if (select count(*) from storage.objects)<>3 then raise exception 'fixture objects mutated'; end if; end $$;
rollback;
