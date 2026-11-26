-- S12: works from the catalogs (TMDB, Open Library), user-created releases, and the duplicate-release check.
--
-- 1. works.catalog_ref: one work per catalog entry ('tmdb_movie:128', 'tmdb_tv:246', 'ol_work:OL27482W'; null for a
--    work a user created). Unique, so two people linking the same film at once get one row (INSERT ... ON CONFLICT).
--    works.created_by: who first linked or created it, kept for moderation, like releases.created_by.
-- 2. created_by is backend only. Every signed-in user may read works and releases, but a user id next to the releases
--    it created is a partial list of what that user owns. Column grants replace the table-wide SELECT: users read the
--    catalog columns only (not created_by, and not the embedding, which is 2 KB a row and of no use to the app).
-- 3. work_from_catalog(): find or create the work for a catalog entry. The first answer wins; an existing work is never
--    changed by it. The API fetches the entry itself, so a user cannot write a title onto a catalog ref.
-- 4. similar_releases(): releases near an embedding (pgvector cosine distance, the HNSW index), for the duplicate check.
--    Releases whose format differs from the new one's are never suggested: the threshold measurement
--    (docs/DUPLICATE_THRESHOLD.md) shows the same film in another format can sit close to a real duplicate.
-- 5. create_user_release(): a shared release (and, when no catalog entry matched, a shared work) made from the catalog
--    facts the owner approved: title, format, edition, and the work's title, year and kind. Never notes, photos,
--    occasions, people, prices or anything else on the item. With a barcode, the unique index decides (ON CONFLICT: the
--    first release wins and is not changed). Without one, an advisory lock serialises creation and the similarity check
--    runs again inside it, so when two people create the same release at once the second is shown the first's
--    ("this looks like an existing release; use it?") instead of making a twin. Releases the owner has already said
--    are different (p_declined) are not suggested again. Nothing is ever merged automatically.
-- 6. link_release_work(): give a release its work when it has none yet (a barcode release from UPCitemdb). Locks the
--    release row, so two people linking at once give it one work; a release that has a work keeps it.
-- All four functions are for the backend's service role only; users still cannot write works or releases.

-- 1 ------------------------------------------------------------------------------------------------------------
alter table public.works
  add column catalog_ref text unique check (catalog_ref ~ '^(tmdb_movie|tmdb_tv|ol_work):[A-Za-z0-9]{1,40}$'),
  add column created_by  uuid references auth.users (id) on delete set null;

-- 2 ------------------------------------------------------------------------------------------------------------
revoke select on public.works, public.releases from authenticated;
grant select (id, title, year, kind, external_ids, catalog_ref, created_at) on public.works to authenticated;
grant select (id, barcode, title, edition, format, region, publisher, release_year, attributes, verified, created_at,
              updated_at) on public.releases to authenticated;

-- 3 ------------------------------------------------------------------------------------------------------------
create function public.work_from_catalog(p_ref text, p_title text, p_year integer, p_kind text, p_external_ids jsonb,
                                         p_created_by uuid)
returns jsonb
language plpgsql volatile set search_path = '' as $$
declare
  v_work    public.works;
  v_created boolean := true;
begin
  if p_ref is null then
    raise exception 'A catalog reference is required' using errcode = '22023';
  end if;
  insert into public.works (catalog_ref, title, year, kind, external_ids, created_by)
  values (p_ref, left(btrim(p_title), 300), p_year, p_kind, coalesce(p_external_ids, '{}'), p_created_by)
  on conflict (catalog_ref) do nothing
  returning * into v_work;
  if v_work.id is null then
    v_created := false;
    select * into v_work from public.works where catalog_ref = p_ref;   -- a new statement: sees the other's commit
  end if;
  return (to_jsonb(v_work) - 'created_by') || jsonb_build_object('created', v_created);
end;
$$;
revoke execute on function public.work_from_catalog(text, text, integer, text, jsonb, uuid) from public, anon, authenticated;
grant execute on function public.work_from_catalog(text, text, integer, text, jsonb, uuid) to service_role;

-- 4 ------------------------------------------------------------------------------------------------------------
-- p_embedding is pgvector's text form ('[0.1,0.2,...]'), which is how it arrives from PostgREST.
create function public.similar_releases(p_embedding text, p_format text, p_max_distance double precision,
                                        p_limit integer default 3)
returns table (id uuid, title text, edition text, format text, release_year integer, barcode text,
               work_title text, work_year integer, distance double precision)
language sql stable set search_path = '' as $$
  with near as (   -- nearest first, from the HNSW index; filtered afterwards
    select r.*, r.embedding operator(extensions.<=>) p_embedding::extensions.vector(512) as distance
    from public.releases r
    where r.embedding is not null
    order by r.embedding operator(extensions.<=>) p_embedding::extensions.vector(512)
    limit 20
  )
  select n.id, n.title, n.edition, n.format, n.release_year, n.barcode, w.title, w.year, n.distance
  from near n
  left join lateral (
    select w.title, w.year from public.release_works rw join public.works w on w.id = rw.work_id
    where rw.release_id = n.id order by rw.position nulls last limit 1
  ) w on true
  where n.distance <= p_max_distance
    and (n.format is null or nullif(btrim(p_format), '') is null or lower(n.format) = lower(btrim(p_format)))
  order by n.distance
  limit greatest(p_limit, 1);
$$;
revoke execute on function public.similar_releases(text, text, double precision, integer) from public, anon, authenticated;
grant execute on function public.similar_releases(text, text, double precision, integer) to service_role;

-- 6 (used by 5) --------------------------------------------------------------------------------------------------
create function public.link_release_work(p_release_id uuid, p_work_id uuid)
returns jsonb
language plpgsql volatile set search_path = '' as $$
declare
  v_existing uuid;
begin
  perform 1 from public.releases where id = p_release_id for update;
  if not found then
    raise exception 'No such release' using errcode = 'PT404';
  end if;
  select work_id into v_existing from public.release_works where release_id = p_release_id
  order by position nulls last limit 1;
  if v_existing is not null then
    return jsonb_build_object('work_id', v_existing, 'linked', false);
  end if;
  insert into public.release_works (release_id, work_id, position) values (p_release_id, p_work_id, 1);
  return jsonb_build_object('work_id', p_work_id, 'linked', true);
end;
$$;
revoke execute on function public.link_release_work(uuid, uuid) from public, anon, authenticated;
grant execute on function public.link_release_work(uuid, uuid) to service_role;

-- 5 ------------------------------------------------------------------------------------------------------------
-- p_work_id: a work the owner picked (from work_from_catalog()). Or p_new_work {title, year, kind}: "none of these",
-- a shared work made from the owner's approved title, year and kind. A user-created work with the same title, kind
-- and year is reused rather than made twice. Or neither: the release has no work.
-- Returns {status: 'created' | 'existing' | 'similar', release, similar: [...]}. 'similar' creates nothing.
create function public.create_user_release(p_title text, p_format text, p_edition text, p_barcode text,
                                           p_embedding text, p_work_id uuid, p_new_work jsonb, p_created_by uuid,
                                           p_max_distance double precision, p_declined uuid[] default '{}')
returns jsonb
language plpgsql volatile set search_path = '' as $$
declare
  v_title   text := left(btrim(coalesce(p_title, '')), 300);
  v_format  text := nullif(left(btrim(coalesce(p_format, '')), 100), '');
  v_edition text := nullif(left(btrim(coalesce(p_edition, '')), 100), '');
  v_similar jsonb;
  v_rel     public.releases;
  v_status  text := 'created';
  v_work    uuid := p_work_id;
  v_wtitle  text;
  v_wyear   integer;
  v_wkind   text;
begin
  if v_title = '' then
    raise exception 'A release needs a title' using errcode = '22023';
  end if;
  if p_work_id is not null and p_new_work is not null then
    raise exception 'Pick a work or describe a new one, not both' using errcode = '22023';
  end if;

  -- One creator at a time. Creating shared rows is rare next to reading them, so one lock is enough at this scale.
  perform pg_advisory_xact_lock(hashtextextended('catalog:user_create', 0));

  if p_barcode is null and p_embedding is not null then
    select coalesce(jsonb_agg(to_jsonb(s) order by s.distance), '[]') into v_similar
    from public.similar_releases(p_embedding, v_format, p_max_distance, 3) s
    where s.id <> all(coalesce(p_declined, '{}'));
    if jsonb_array_length(v_similar) > 0 then
      return jsonb_build_object('status', 'similar', 'release', null, 'similar', v_similar);
    end if;
  end if;

  if p_new_work is not null then
    v_wtitle := left(btrim(coalesce(p_new_work ->> 'title', '')), 300);
    v_wyear  := (p_new_work ->> 'year')::integer;
    v_wkind  := coalesce(p_new_work ->> 'kind', 'other');
    if v_wtitle = '' then
      raise exception 'A work needs a title' using errcode = '22023';
    end if;
    select id into v_work from public.works
    where catalog_ref is null and lower(title) = lower(v_wtitle) and kind = v_wkind and year is not distinct from v_wyear
    order by created_at limit 1;
    if v_work is null then
      insert into public.works (title, year, kind, created_by) values (v_wtitle, v_wyear, v_wkind, p_created_by)
      returning id into v_work;
    end if;
  end if;

  insert into public.releases (barcode, title, format, edition, attributes, created_by, embedding)
  values (p_barcode, v_title, v_format, v_edition, '{"source": "user"}', p_created_by,
          p_embedding::extensions.vector(512))
  on conflict (barcode) do nothing
  returning * into v_rel;
  if v_rel.id is null then      -- a barcode someone else's release already has: theirs stands, unchanged
    v_status := 'existing';
    select * into v_rel from public.releases
    where barcode = case when length(p_barcode) = 12 then '0' || p_barcode else p_barcode end;
  end if;

  if v_work is not null then
    perform public.link_release_work(v_rel.id, v_work);
  end if;
  return jsonb_build_object('status', v_status, 'release', to_jsonb(v_rel) - 'embedding' - 'created_by',
                            'similar', '[]'::jsonb);
end;
$$;
revoke execute on function public.create_user_release(text, text, text, text, text, uuid, jsonb, uuid, double precision, uuid[])
  from public, anon, authenticated;
grant execute on function public.create_user_release(text, text, text, text, text, uuid, jsonb, uuid, double precision, uuid[])
  to service_role;
