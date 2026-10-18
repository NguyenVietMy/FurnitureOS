-- Storage 1.80.2 performs authenticated-info and authenticated-download reads.
-- Permit only those two phases; preserve every Capture identity/lifecycle predicate.
-- Applied migration history remains immutable. Apply only after fresh inspection.
alter policy capture_private_download on storage.objects using
 ((select private.capture_anonymous_owner()) and bucket_id='captures' and
 (storage.allow_only_operation('object.get_authenticated_info') or
  storage.allow_only_operation('object.get_authenticated')) and
 (storage.foldername(name))[1]=(select auth.uid()::text) and
 exists(select 1 from public.capture_photos p join public.captures c on c.id=p.capture_id and c.owner_id=p.owner_id
  where p.object_key=name and p.owner_id=(select auth.uid()) and p.state='accepted' and c.state<>'deleting' and c.expires_at>now()));
