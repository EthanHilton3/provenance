-- Provenance: private storage bucket for photos (docs/DESIGN.md, "Security, scaling and costs").
--
-- Object path: <owner_id>/<photo_id>.jpg, the same prefix public.photos.storage_path is checked against
-- (`storage_path like owner_id::text || '/%'`). The storage policies below use the same prefix, so the
-- database row and the file are protected by the same rule: only the owner.
--
-- The backend always re-encodes uploads as JPEG, so the bucket only accepts image/jpeg, up to 5 MiB
-- (a 2048 px JPEG is well under 1 MiB). Files are read through short-lived signed URLs, never public ones.

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('photos', 'photos', false, 5242880, array['image/jpeg'])
on conflict (id) do update
  set public = false, file_size_limit = excluded.file_size_limit, allowed_mime_types = excluded.allowed_mime_types;

-- Own prefix only, for read, write and delete. No update policy: nothing needs to overwrite a photo
-- (each upload gets a new id), so there is nothing to allow. anon gets no policy and so no access.
create policy photos_objects_read on storage.objects for select to authenticated
  using (bucket_id = 'photos' and (storage.foldername(name))[1] = (select auth.uid())::text);

create policy photos_objects_insert on storage.objects for insert to authenticated
  with check (bucket_id = 'photos' and (storage.foldername(name))[1] = (select auth.uid())::text);

create policy photos_objects_delete on storage.objects for delete to authenticated
  using (bucket_id = 'photos' and (storage.foldername(name))[1] = (select auth.uid())::text);
