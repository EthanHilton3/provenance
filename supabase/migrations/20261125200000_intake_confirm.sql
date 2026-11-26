-- S10: confirming, discarding and retrying intake jobs, and batch occasions.
--
-- 1. items.sealed may be null: "not recorded". The models often cannot tell sealed from opened, and a card the owner
--    has not answered must not save a guess as a fact. Existing rows keep their value.
-- 2. intake_jobs.status gains discarded. A discarded job keeps its row (and its card, for the S13 accuracy log) so
--    it still counts toward the daily limit; its photo is deleted by the API.
-- 3. items.intake_job_id: which job an item came from. A group photo yields many items, so the link lives on the
--    item; intake_jobs.item_id keeps pointing at the first one.
-- 4. intake_jobs.retried_at: a manual retry counts as one more photo toward the daily limit (intake_photos_today()).
-- 5. create_intake_jobs() takes an optional occasion for the whole batch ("these are all from Christmas 2025").
-- 6. confirm_intake_job(), discard_intake_job(), retry_intake_job(): users cannot write intake_jobs directly (the
--    initial schema revokes it), so these run as their owner, take the user from auth.uid() only, and lock the job
--    row FOR UPDATE first. Two confirms of one job (double tap, two tabs) are serialised by that lock; the second
--    sees status done and gets a 409, so items are never created twice.
--
-- confirm_intake_job() bypasses RLS (it is security definer), so it re-checks by hand everything the items policy
-- would: the owner is auth.uid(), never input; the category is built-in or one the caller owns. Occasion, giver and
-- parent item are same-owner composite foreign keys, which hold regardless of RLS.

-- 1 ------------------------------------------------------------------------------------------------------------
alter table public.items alter column sealed drop not null, alter column sealed drop default;

-- 2 ------------------------------------------------------------------------------------------------------------
alter table public.intake_jobs drop constraint intake_jobs_status_check;
alter table public.intake_jobs add constraint intake_jobs_status_check
  check (status in ('queued', 'processing', 'needs_review', 'done', 'failed', 'discarded'));

-- 3 and 4 ------------------------------------------------------------------------------------------------------
alter table public.items add column intake_job_id uuid;
alter table public.items add constraint items_intake_job_fk
  foreign key (owner_id, intake_job_id) references public.intake_jobs (owner_id, id) on delete set null (intake_job_id);
create index items_intake_job_idx on public.items (owner_id, intake_job_id) where intake_job_id is not null;

alter table public.intake_jobs add column retried_at timestamptz;

-- Photos sent to the AI in the last day: jobs created, plus jobs retried by hand.
create function public.intake_photos_today(p_owner uuid) returns integer
language sql stable set search_path = '' as $$
  select (count(*) filter (where created_at > now() - interval '1 day')
        + count(*) filter (where retried_at > now() - interval '1 day'))::integer
  from public.intake_jobs where owner_id = p_owner;
$$;
revoke execute on function public.intake_photos_today(uuid) from public, anon, authenticated;

-- 5 ------------------------------------------------------------------------------------------------------------
drop function public.create_intake_jobs(uuid[], text);

create function public.create_intake_jobs(p_photo_ids uuid[], p_mode text, p_occasion_id uuid default null)
returns setof public.intake_jobs
language plpgsql volatile security definer set search_path = '' as $$
declare
  v_owner  uuid := auth.uid();
  v_ids    uuid[];
  v_found  integer;
  v_used   integer;
  v_photo  uuid;
  v_job    public.intake_jobs;
  c_daily  constant integer := 200;   -- photos a day per user (design: abuse and cost limits)
begin
  if v_owner is null then
    raise exception 'Sign in to add photos' using errcode = '42501';
  end if;
  if p_mode is null or p_mode not in ('single', 'group') then
    raise exception 'mode must be single or group' using errcode = '22023';
  end if;
  v_ids := array(select x from unnest(p_photo_ids) with ordinality t(x, n) where x is not null group by x order by min(n));
  if cardinality(v_ids) not between 1 and 50 then
    raise exception 'Send between 1 and 50 photos' using errcode = '22023';
  end if;
  if p_occasion_id is not null
     and not exists (select 1 from public.occasions where id = p_occasion_id and owner_id = v_owner) then
    raise exception 'Occasion not found' using errcode = 'PT404';
  end if;

  perform pg_advisory_xact_lock(hashtextextended('intake_jobs:' || v_owner::text, 0));

  select count(*) into v_found from (
    select 1 from public.photos where id = any(v_ids) and owner_id = v_owner for update
  ) mine;
  if v_found < cardinality(v_ids) then
    raise exception 'Photo not found' using errcode = 'PT404';
  end if;
  if exists (select 1 from public.photos
             where id = any(v_ids) and (item_id is not null or intake_job_id is not null)) then
    raise exception 'A photo is already on an item or in intake' using errcode = 'PT409';
  end if;

  v_used := public.intake_photos_today(v_owner);
  if v_used + cardinality(v_ids) > c_daily then
    raise exception 'Daily limit of % photos reached; % left today', c_daily, greatest(c_daily - v_used, 0)
      using errcode = 'PT429';
  end if;

  foreach v_photo in array v_ids loop
    insert into public.intake_jobs (owner_id, mode, occasion_id) values (v_owner, p_mode, p_occasion_id)
    returning * into v_job;
    update public.photos set intake_job_id = v_job.id where id = v_photo and owner_id = v_owner;
    return next v_job;
  end loop;
end;
$$;
revoke execute on function public.create_intake_jobs(uuid[], text, uuid) from public, anon;
grant execute on function public.create_intake_jobs(uuid[], text, uuid) to authenticated;

-- 6 ------------------------------------------------------------------------------------------------------------

-- The job of the caller, locked for the rest of the transaction. A job of another user is "not found", never "not yours".
create function public.lock_own_intake_job(p_job_id uuid) returns public.intake_jobs
language plpgsql volatile set search_path = '' as $$
declare
  v_job public.intake_jobs;
begin
  if auth.uid() is null then
    raise exception 'Sign in first' using errcode = '42501';
  end if;
  select * into v_job from public.intake_jobs where id = p_job_id and owner_id = auth.uid() for update;
  if not found then
    raise exception 'No such intake job' using errcode = 'PT404';
  end if;
  return v_job;
end;
$$;
revoke execute on function public.lock_own_intake_job(uuid) from public, anon, authenticated;

-- Saves the confirmed items of the owner for one job, links the photo of the job to them and marks the job done, in one
-- transaction. p_items: 1 to 100 item objects (the API has already validated each against ItemCreate; the
-- table checks apply again here). p_copies: [{id, storage_path}], one copy of the photo file of the job for each item after
-- the first, made by the API before this call; the first item gets the original. Width, height and date taken are
-- copied from the original row, not taken from input.
create function public.confirm_intake_job(p_job_id uuid, p_items jsonb, p_copies jsonb default '[]')
returns setof public.items
language plpgsql volatile security definer set search_path = '' as $$
declare
  v_owner   uuid := auth.uid();
  v_job     public.intake_jobs;
  v_n       integer;
  v_obj     jsonb;
  v_cat     uuid;
  v_item    public.items;
  v_items   uuid[] := '{}';
  v_photo   public.photos;
  v_copy    jsonb;
  v_path    text;
  v_expected integer;
  i         integer;
begin
  v_job := public.lock_own_intake_job(p_job_id);
  if v_job.status = 'done' then
    raise exception 'These items are already saved' using errcode = 'PT409';
  elsif v_job.status = 'discarded' then
    raise exception 'This photo was discarded' using errcode = 'PT409';
  elsif v_job.status not in ('needs_review', 'failed') then
    raise exception 'The AI is still reading this photo' using errcode = 'PT409';
  end if;

  if jsonb_typeof(p_items) is distinct from 'array' then
    raise exception 'Send between 1 and 100 items' using errcode = '22023';
  end if;
  v_n := jsonb_array_length(p_items);
  if v_n not between 1 and 100 then
    raise exception 'Send between 1 and 100 items' using errcode = '22023';
  end if;
  p_copies := coalesce(p_copies, '[]');
  if jsonb_typeof(p_copies) <> 'array' then
    raise exception 'copies must be a list' using errcode = '22023';
  end if;

  select * into v_photo from public.photos
  where intake_job_id = v_job.id and owner_id = v_owner and item_id is null
  order by position, created_at limit 1;
  v_expected := case when v_photo.id is null then 0 else v_n - 1 end;
  if jsonb_array_length(p_copies) <> v_expected then
    raise exception 'Expected one photo copy for each item after the first' using errcode = '22023';
  end if;

  for i in 0 .. v_n - 1 loop
    v_obj := p_items -> i;
    if jsonb_typeof(v_obj) is distinct from 'object' then
      raise exception 'Item % is not an object', i + 1 using errcode = '22023';
    end if;
    v_cat := (v_obj ->> 'category_id')::uuid;
    if not exists (select 1 from public.categories c
                   where c.id = v_cat and (c.owner_id is null or c.owner_id = v_owner)) then
      raise exception 'Item %: no such category', i + 1 using errcode = 'PT422';
    end if;
    insert into public.items (
      owner_id, intake_job_id, name, category_id, release_id, parent_item_id, occasion_id, giver_id, source,
      acquired_on, date_is_approximate, condition_grade, sealed, intent, thank_you_sent, price_paid, location, notes,
      franchise, brand, signed_by, attributes)
    values (
      v_owner, v_job.id, v_obj ->> 'name', v_cat, (v_obj ->> 'release_id')::uuid, (v_obj ->> 'parent_item_id')::uuid,
      (v_obj ->> 'occasion_id')::uuid, (v_obj ->> 'giver_id')::uuid, v_obj ->> 'source',
      (v_obj ->> 'acquired_on')::date, coalesce((v_obj ->> 'date_is_approximate')::boolean, false),
      v_obj ->> 'condition_grade', (v_obj ->> 'sealed')::boolean, coalesce(v_obj ->> 'intent', 'keep'),
      coalesce((v_obj ->> 'thank_you_sent')::boolean, false), (v_obj ->> 'price_paid')::numeric,
      v_obj ->> 'location', v_obj ->> 'notes', v_obj ->> 'franchise', v_obj ->> 'brand', v_obj ->> 'signed_by',
      coalesce(v_obj -> 'attributes', '{}'))
    returning * into v_item;
    v_items := v_items || v_item.id;
    return next v_item;
  end loop;

  if v_photo.id is not null then
    -- Every photo still on the job goes to the first item (one today; S11 may add a barcode photo).
    update public.photos set item_id = v_items[1]
    where intake_job_id = v_job.id and owner_id = v_owner and item_id is null;
    for i in 1 .. v_n - 1 loop
      v_copy := p_copies -> (i - 1);
      v_path := v_copy ->> 'storage_path';
      if v_path is null or v_path not like v_owner::text || '/%' then
        raise exception 'A photo copy is not in your folder' using errcode = '42501';
      end if;
      insert into public.photos (id, owner_id, item_id, intake_job_id, storage_path, taken_at, width, height, position)
      values ((v_copy ->> 'id')::uuid, v_owner, v_items[i + 1], v_job.id, v_path, v_photo.taken_at, v_photo.width,
              v_photo.height, 0);
    end loop;
  end if;

  update public.intake_jobs
  set status = 'done', item_id = v_items[1], error = null, locked_by = null, locked_at = null
  where id = v_job.id;
end;
$$;
revoke execute on function public.confirm_intake_job(uuid, jsonb, jsonb) from public, anon;
grant execute on function public.confirm_intake_job(uuid, jsonb, jsonb) to authenticated;

-- Marks the job discarded and returns its photos that are on no item, for the API to delete (file, then row).
-- Discarding an already discarded job returns whatever is left, so a half-finished cleanup can be finished.
create function public.discard_intake_job(p_job_id uuid)
returns table (photo_id uuid, storage_path text)
language plpgsql volatile security definer set search_path = '' as $$
declare
  v_job public.intake_jobs;
begin
  v_job := public.lock_own_intake_job(p_job_id);
  if v_job.status = 'done' then
    raise exception 'These items are already saved; delete them from the item page' using errcode = 'PT409';
  elsif v_job.status = 'processing' then
    raise exception 'The AI is reading this photo right now; try again in a moment' using errcode = 'PT409';
  elsif v_job.status <> 'discarded' then
    update public.intake_jobs set status = 'discarded', run_after = now(), locked_by = null, locked_at = null
    where id = v_job.id;
  end if;
  return query
    select p.id, p.storage_path from public.photos p
    where p.intake_job_id = v_job.id and p.owner_id = v_job.owner_id and p.item_id is null;
end;
$$;
revoke execute on function public.discard_intake_job(uuid) from public, anon;
grant execute on function public.discard_intake_job(uuid) to authenticated;

-- A failed job goes back in the queue with fresh attempts. It counts as one more photo toward the daily limit.
create function public.retry_intake_job(p_job_id uuid) returns setof public.intake_jobs
language plpgsql volatile security definer set search_path = '' as $$
declare
  v_job   public.intake_jobs;
  v_used  integer;
  c_daily constant integer := 200;
begin
  -- Same per-user lock as create_intake_jobs(), so a retry and an upload cannot both slip under the limit.
  perform pg_advisory_xact_lock(hashtextextended('intake_jobs:' || coalesce(auth.uid()::text, ''), 0));
  v_job := public.lock_own_intake_job(p_job_id);
  if v_job.status <> 'failed' then
    raise exception 'Only a failed photo can be retried' using errcode = 'PT409';
  end if;
  if not exists (select 1 from public.photos where intake_job_id = v_job.id and owner_id = v_job.owner_id) then
    raise exception 'The photo for this job is gone; add the item by hand' using errcode = 'PT409';
  end if;
  v_used := public.intake_photos_today(v_job.owner_id);
  if v_used + 1 > c_daily then
    raise exception 'Daily limit of % photos reached', c_daily using errcode = 'PT429';
  end if;
  return query
    update public.intake_jobs
    set status = 'queued', attempts = 0, run_after = now(), error = null, card = null, locked_by = null,
        locked_at = null, retried_at = now()
    where id = v_job.id
    returning *;
end;
$$;
revoke execute on function public.retry_intake_job(uuid) from public, anon;
grant execute on function public.retry_intake_job(uuid) to authenticated;
