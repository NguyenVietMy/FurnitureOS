-- Activation is explicit: defining this installer does not create or enable a cron job.
create function private.capture_install_schedule(p_function_url text,p_vault_secret_name text)
returns void language plpgsql security definer set search_path='' as $$
begin
 if p_function_url !~ '^https://[^/]+/functions/v1/capture-cleanup$' or length(p_vault_secret_name)>100 then raise exception 'invalid-cleanup-target'; end if;
 if not exists(select 1 from pg_extension where extname='pg_cron') or not exists(select 1 from pg_extension where extname='pg_net') then raise exception 'activation-required'; end if;
 execute format($schedule$select cron.schedule('capture-cleanup-v1','*/15 * * * *',%L)$schedule$,
  format($call$select net.http_post(url:=%L,headers:=jsonb_build_object('Content-Type','application/json','x-capture-cleanup-scheduled','1','x-capture-cleanup-secret',(select decrypted_secret from vault.decrypted_secrets where name=%L limit 1)),body:='{}'::jsonb,timeout_milliseconds:=70000)$call$,p_function_url,p_vault_secret_name));
end $$;
create function public.capture_install_schedule(p_function_url text,p_vault_secret_name text)
returns void language sql security invoker set search_path='' as $$
 select private.capture_install_schedule(p_function_url,p_vault_secret_name)
$$;
revoke execute on function private.capture_install_schedule(text,text),public.capture_install_schedule(text,text) from public,anon,authenticated;
grant execute on function private.capture_install_schedule(text,text),public.capture_install_schedule(text,text) to service_role;
