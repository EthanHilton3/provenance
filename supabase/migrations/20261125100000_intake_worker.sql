-- S9: the intake queue's API side and worker side.
--
-- 1. intake_jobs.mode: 'single' (one item per photo, Luna) or 'group' (many items in one photo, Sol).
-- 2. intake_jobs.usage: model, tokens and cost summed over every attempt (a failed attempt costs money too).
--    The worker's result stays in the existing intake_jobs.card column (one jsonb proposal per job).
-- 3. create_intake_jobs(): how a signed-in user queues photos. Users still cannot insert into intake_jobs directly
--    (the initial schema revokes it, because a direct insert would skip the daily limit and spend AI money). This
--    function runs as its owner but takes the user from auth.uid() only, checks every photo is the caller's and
--    not already used, applies the daily limit, and links each photo to its job, all in one transaction.
-- 4. fail_stale_intake_jobs(): claim_intake_job() retries a crashed worker's job after the lease, but only while
--    attempts < max_attempts. A worker that crashes on the LAST attempt would leave the job in 'processing' forever;
--    this marks those failed with a readable reason. Workers call it before each claim.

alter table public.intake_jobs
  add column mode  text not null default 'single' check (mode in ('single', 'group')),
  add column usage jsonb check (usage is null or jsonb_typeof(usage) = 'object');

create function public.create_intake_jobs(p_photo_ids uuid[], p_mode text)
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
  -- Distinct ids, in the order given.
  v_ids := array(select x from unnest(p_photo_ids) with ordinality t(x, n) where x is not null group by x order by min(n));
  if cardinality(v_ids) not between 1 and 50 then
    raise exception 'Send between 1 and 50 photos' using errcode = '22023';
  end if;

  -- One request per user at a time, so two parallel requests cannot both slip under the daily limit.
  perform pg_advisory_xact_lock(hashtextextended('intake_jobs:' || v_owner::text, 0));

  -- Lock the caller's photos. Someone else's photo is "not found", never "not yours".
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

  select count(*) into v_used from public.intake_jobs
  where owner_id = v_owner and created_at > now() - interval '1 day';
  if v_used + cardinality(v_ids) > c_daily then
    raise exception 'Daily limit of % photos reached; % left today', c_daily, greatest(c_daily - v_used, 0)
      using errcode = 'PT429';
  end if;

  foreach v_photo in array v_ids loop
    insert into public.intake_jobs (owner_id, mode) values (v_owner, p_mode) returning * into v_job;
    update public.photos set intake_job_id = v_job.id where id = v_photo and owner_id = v_owner;
    return next v_job;
  end loop;
end;
$$;
revoke execute on function public.create_intake_jobs(uuid[], text) from public, anon;
grant execute on function public.create_intake_jobs(uuid[], text) to authenticated;

create function public.fail_stale_intake_jobs(p_lease interval default interval '5 minutes')
returns integer
language sql volatile set search_path = '' as $$
  with failed as (
    update public.intake_jobs
    set status = 'failed', locked_by = null, locked_at = null,
        error = 'The worker stopped while reading this photo (' || attempts || ' tries). Try again or add it by hand.'
    where status = 'processing' and attempts >= max_attempts and locked_at < now() - p_lease
    returning 1
  )
  select count(*)::integer from failed;
$$;
revoke execute on function public.fail_stale_intake_jobs(interval) from public, anon, authenticated;
grant execute on function public.fail_stale_intake_jobs(interval) to service_role;
