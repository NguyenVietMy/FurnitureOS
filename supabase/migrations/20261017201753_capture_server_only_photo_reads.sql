-- Empty development cutover only. Never remove data to satisfy this guard.
do $$
begin
  if exists (select 1 from public.captures)
     or exists (select 1 from storage.objects where bucket_id = 'captures')
     or exists (select 1 from private.capture_cleanup_jobs) then
    raise exception 'capture-server-photo-cutover-requires-empty';
  end if;
end $$;

drop policy capture_private_download on storage.objects;

-- Restrictive policies are ANDed with every applicable permissive policy.
-- Other buckets retain their existing policies; trusted service/worker access
-- still uses its existing RLS bypass. Caller metadata policies are unchanged.
create policy capture_server_only_photo_reads on storage.objects
  as restrictive for select to anon, authenticated
  using (bucket_id <> 'captures');
