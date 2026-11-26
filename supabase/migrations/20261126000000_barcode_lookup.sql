-- S11: barcode lookup. A scanned, typed or model-read barcode finds a shared release by its unique index, then the
-- catalog cache, then UPCitemdb; a hit becomes a shared release (INSERT ... ON CONFLICT, so two people scanning the
-- same new barcode at once get one row).
--
-- 1. gtin_valid(): the GTIN check digit (UPC-A, EAN-13, EAN-8, GTIN-14 all use the same mod-10 rule). The barcode
--    test caught a model misreading one digit this way. Releases and intake jobs may only hold barcodes that pass, so
--    no path (scan, typed, model-read, a future import) can store a misread code. The API checks first and expands
--    UPC-E to UPC-A; a raw 8-digit UPC-E fails this check and is refused rather than stored as a second product.
-- 2. catalog_calls: one row per call to an outside catalog, backend only. begin_catalog_call() is the budget gate:
--    UPCitemdb's free tier is about 100 lookups a day for the whole app, so it is shared, with a per-user share so
--    one user cannot use it up, a per-minute cap (its per-minute limit is undocumented) and a cool-down after a 429.
-- 3. release_from_catalog(): find or create the shared release for a barcode from catalog data. Backend only;
--    users still cannot write releases at all (the initial schema revokes it). An existing release is never changed
--    by it: the first catalog answer wins and later scans only read it.
-- 4. create_intake_jobs() takes an optional barcode: "photograph the box" after a lookup miss keeps the code with the
--    photo (intake_jobs.barcode). Shared releases made from what a user types are S12, not here.

-- 1 ------------------------------------------------------------------------------------------------------------
create function public.gtin_valid(p_code text) returns boolean
language sql immutable strict parallel safe set search_path = '' as $$
  select case
    when p_code !~ '^([0-9]{8}|[0-9]{12,14})$' then false
    else (
      -- Weights 3, 1, 3, 1... starting with the digit just left of the check digit.
      select (10 - sum(substr(p_code, length(p_code) - i, 1)::integer * case when i % 2 = 1 then 3 else 1 end) % 10) % 10
      from generate_series(1, length(p_code) - 1) as i
    ) = right(p_code, 1)::integer
  end;
$$;

-- The trigger normalizes first (UPC-A -> EAN-13), then this runs on the stored value.
alter table public.releases add constraint releases_barcode_check_digit
  check (barcode is null or public.gtin_valid(barcode));
alter table public.intake_jobs add constraint intake_jobs_barcode_check
  check (barcode is null or (barcode ~ '^([0-9]{8}|[0-9]{13}|[0-9]{14})$' and public.gtin_valid(barcode)));

-- 2 ------------------------------------------------------------------------------------------------------------
create table public.catalog_calls (
  id           bigint generated always as identity primary key,
  provider     text not null,                                   -- 'upcitemdb'
  user_id      uuid references auth.users (id) on delete set null,
  called_at    timestamptz not null default now(),
  http_status  integer,                                         -- null: no answer (timeout, network)
  outcome      text not null default 'pending' check (outcome in ('pending', 'hit', 'miss', 'rate_limited', 'error')),
  retry_after  timestamptz                                      -- set from a 429: no calls before this
);
create index catalog_calls_provider_idx on public.catalog_calls (provider, called_at desc);
alter table public.catalog_calls enable row level security;   -- no policies: service role only
revoke all on public.catalog_calls from anon, authenticated;

-- Reserves one call, or raises. Every reserved call counts, whatever its outcome: the provider counted it too.
-- errcode PT429 with detail 'daily' (the app's budget is spent) or 'user' (this user's share is); PT503 with detail
-- 'cooldown' (a 429 asked us to wait) or 'minute' (too many in the last minute). The advisory lock makes the count
-- and the insert one step, so concurrent lookups cannot both take the last call.
create function public.begin_catalog_call(p_provider text, p_user uuid, p_daily integer, p_per_user integer,
                                          p_per_minute integer)
returns bigint
language plpgsql volatile set search_path = '' as $$
declare
  v_until  timestamptz;
  v_day    integer;
  v_mine   integer;
  v_minute integer;
  v_id     bigint;
begin
  perform pg_advisory_xact_lock(hashtextextended('catalog_calls:' || p_provider, 0));
  select max(retry_after),
         count(*),
         count(*) filter (where user_id = p_user),
         count(*) filter (where called_at > now() - interval '1 minute')
  into v_until, v_day, v_mine, v_minute
  from public.catalog_calls
  where provider = p_provider and called_at > now() - interval '1 day';

  if v_until > now() then
    raise exception 'The catalog asked us to slow down; try again in % s', ceil(extract(epoch from v_until - now()))::integer
      using errcode = 'PT503', detail = 'cooldown';
  end if;
  if v_day >= p_daily then
    raise exception 'Barcode lookups are used up for today' using errcode = 'PT429', detail = 'daily';
  end if;
  if p_user is not null and v_mine >= p_per_user then
    raise exception 'You have used your % barcode lookups for today', p_per_user using errcode = 'PT429', detail = 'user';
  end if;
  if v_minute >= p_per_minute then
    raise exception 'Too many barcode lookups this minute; try again shortly' using errcode = 'PT503', detail = 'minute';
  end if;

  insert into public.catalog_calls (provider, user_id) values (p_provider, p_user) returning id into v_id;
  return v_id;
end;
$$;
revoke execute on function public.begin_catalog_call(text, uuid, integer, integer, integer) from public, anon, authenticated;
grant execute on function public.begin_catalog_call(text, uuid, integer, integer, integer) to service_role;

-- 3 ------------------------------------------------------------------------------------------------------------
-- Returns the release (without its embedding) plus "created": true if this call made it. Catalog text is untrusted:
-- it is trimmed and cut to length here as well as in the API, and stored only as data. The follow-up select is a
-- separate statement, so under READ COMMITTED it sees a row another transaction committed while this one waited on
-- the unique index.
create function public.release_from_catalog(p_barcode text, p_title text, p_publisher text, p_attributes jsonb,
                                            p_created_by uuid)
returns jsonb
language plpgsql volatile set search_path = '' as $$
declare
  v_rel     public.releases;
  v_created boolean := true;
begin
  if p_barcode is null then
    raise exception 'A barcode is required' using errcode = '22023';
  end if;
  insert into public.releases (barcode, title, publisher, attributes, created_by)
  values (p_barcode, left(btrim(p_title), 300), nullif(left(btrim(p_publisher), 200), ''),
          coalesce(p_attributes, '{}'), p_created_by)
  on conflict (barcode) do nothing
  returning * into v_rel;
  if v_rel.id is null then
    v_created := false;
    -- The trigger normalized the inserted value; look it up the same way.
    select * into v_rel from public.releases
    where barcode = case when length(p_barcode) = 12 then '0' || p_barcode else p_barcode end;
  end if;
  return (to_jsonb(v_rel) - 'embedding') || jsonb_build_object('created', v_created);
end;
$$;
revoke execute on function public.release_from_catalog(text, text, text, jsonb, uuid) from public, anon, authenticated;
grant execute on function public.release_from_catalog(text, text, text, jsonb, uuid) to service_role;

-- 4 ------------------------------------------------------------------------------------------------------------
drop function public.create_intake_jobs(uuid[], text, uuid);

-- As in S10, plus p_barcode: one photo of one item whose barcode the catalog did not know.
create function public.create_intake_jobs(p_photo_ids uuid[], p_mode text, p_occasion_id uuid default null,
                                          p_barcode text default null)
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
  if p_barcode is not null and (p_mode <> 'single' or cardinality(v_ids) <> 1) then
    raise exception 'A barcode goes with one photo of one item' using errcode = '22023';
  end if;
  if p_barcode is not null and not public.gtin_valid(p_barcode) then
    raise exception 'That barcode does not pass its check digit' using errcode = '22023';
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
    insert into public.intake_jobs (owner_id, mode, occasion_id, barcode) values (v_owner, p_mode, p_occasion_id, p_barcode)
    returning * into v_job;
    update public.photos set intake_job_id = v_job.id where id = v_photo and owner_id = v_owner;
    return next v_job;
  end loop;
end;
$$;
revoke execute on function public.create_intake_jobs(uuid[], text, uuid, text) from public, anon;
grant execute on function public.create_intake_jobs(uuid[], text, uuid, text) to authenticated;
