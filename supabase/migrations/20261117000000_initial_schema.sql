-- Provenance: initial schema (docs/DESIGN.md, "Data model" and "Security, scaling and costs").
--
-- Three levels:  works (a title)  ->  releases (one edition, barcode-keyed, shared)  ->  items (my copy, private).
--
-- Access model, enforced here rather than in app code:
--   * Private tables (items, photos, occasions, people, collections, collection_items, wishlist, intake_jobs):
--     RLS `owner_id = auth.uid()`. The backend calls them with the signed-in user's token, so the
--     policies apply to backend queries too.
--   * Shared tables (works, releases, release_works, sets, set_members, built-in categories): readable by
--     signed-in users; only the backend's service role writes them (no write policies, writes revoked).
--   * catalog_cache: backend only.
--   * anon gets nothing except get_shared_collection(token).
--   * Links between private rows use composite foreign keys on (owner_id, id), so an item can never point at
--     another user's occasion, person, parent item or collection, even though FK checks skip RLS.

create extension if not exists pgcrypto with schema extensions;
create extension if not exists pg_trgm  with schema extensions;
create extension if not exists vector   with schema extensions;

-- ============================================================
-- Helper triggers
-- ============================================================

create function public.touch_updated_at() returns trigger
language plpgsql set search_path = '' as $$
begin
  new.updated_at := now();
  return new;
end;
$$;

-- Optimistic locking. The client updates with `... where id = $1 and version = $read_version`; zero rows
-- updated means someone else saved first. The trigger always bumps the version, so a client can't set it.
create function public.bump_version() returns trigger
language plpgsql set search_path = '' as $$
begin
  new.version := old.version + 1;
  new.updated_at := now();
  return new;
end;
$$;

-- ============================================================
-- Categories (tree; owner_id null = built-in)
-- ============================================================

create table public.categories (
  id              uuid primary key default gen_random_uuid(),
  owner_id        uuid references auth.users (id) on delete cascade,   -- null = built-in, shared by everyone
  parent_id       uuid references public.categories (id) on delete restrict,
  name            text not null check (length(btrim(name)) between 1 and 80),
  -- Fields for this kind of thing; children inherit their ancestors' fields (see category_fields()).
  -- Shape: [{"key": "format", "label": "Format", "type": "text|number|boolean|choice", "options": [...]}]
  field_template  jsonb not null default '[]' check (jsonb_typeof(field_template) = 'array'),
  created_at      timestamptz not null default now(),
  check (parent_id <> id),
  unique nulls not distinct (owner_id, parent_id, name)
);
create index categories_parent_idx on public.categories (parent_id);

-- A user's category may sit under a built-in one or one of their own; built-ins only under built-ins.
-- (A trigger, not a policy: a policy on categories that queries categories recurses.)
create function public.check_category_parent() returns trigger
language plpgsql set search_path = '' as $$
begin
  if new.parent_id is not null and not exists (
    select 1 from public.categories p
    where p.id = new.parent_id and (p.owner_id is null or p.owner_id = new.owner_id)
  ) then
    raise exception 'parent category % is not built-in or yours', new.parent_id using errcode = 'foreign_key_violation';
  end if;
  return new;
end;
$$;
create trigger categories_check_parent before insert or update of parent_id, owner_id on public.categories
  for each row execute function public.check_category_parent();

-- Fields for a category, root first, so a child's own definition of a key wins.
create function public.category_fields(p_category_id uuid) returns jsonb
language sql stable set search_path = '' as $$
  with recursive chain as (
    select id, parent_id, field_template, 0 as depth from public.categories where id = p_category_id
    union all
    select c.id, c.parent_id, c.field_template, chain.depth + 1
    from public.categories c join chain on c.id = chain.parent_id
  ),
  fields as (
    select distinct on (f ->> 'key') f, depth, ord
    from chain, jsonb_array_elements(field_template) with ordinality as t(f, ord)
    order by f ->> 'key', depth   -- nearest definition of each key
  )
  select coalesce(jsonb_agg(f order by depth desc, ord), '[]') from fields;
$$;

-- ============================================================
-- Shared catalog: works, releases, sets
-- ============================================================

create table public.works (
  id            uuid primary key default gen_random_uuid(),
  title         text not null check (length(btrim(title)) > 0),
  year          integer check (year between 1000 and 3000),
  kind          text not null check (kind in ('movie', 'tv', 'book', 'game', 'album', 'board_game', 'other')),
  external_ids  jsonb not null default '{}' check (jsonb_typeof(external_ids) = 'object'),  -- {"tmdb_movie": 11, ...}
  created_at    timestamptz not null default now()
);
create index works_title_trgm_idx on public.works using gin (title extensions.gin_trgm_ops);

create table public.releases (
  id            uuid primary key default gen_random_uuid(),
  -- Digits only, stored as EAN-8, EAN-13 or GTIN-14 (UPC-A is padded to EAN-13 by normalize_barcode()).
  -- Null for releases without one; Postgres unique allows many nulls.
  barcode       text unique check (barcode ~ '^([0-9]{8}|[0-9]{13}|[0-9]{14})$'),
  title         text not null check (length(btrim(title)) > 0),     -- "Star Wars: A New Hope (4K steelbook)"
  edition       text,                                              -- steelbook, Deluxe XL, Collector's
  format        text,                                              -- 4K UHD, Blu-ray, Switch cartridge, hardcover
  region        text,
  publisher     text,
  release_year  integer check (release_year between 1000 and 3000),
  attributes    jsonb not null default '{}' check (jsonb_typeof(attributes) = 'object'),
  verified      boolean not null default false,                    -- user-created releases start unverified
  created_by    uuid references auth.users (id) on delete set null, -- kept for moderation
  -- Duplicate detection for releases without a barcode: OpenAI text-embedding-3-small with dimensions=512
  -- over "title | edition | format | publisher | year". Why 512 and not the full 1536: the text is a short
  -- product line and the check only needs to spot near-identical releases, which the shortened (Matryoshka)
  -- vectors keep; 512 floats are 2 KB a row instead of 6 KB on the table that grows with every user's scans,
  -- and the HNSW index is smaller and faster. Same OpenAI key as intake. Changing it later means re-embedding.
  embedding     extensions.vector(512),
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);
create index releases_embedding_idx on public.releases using hnsw (embedding extensions.vector_cosine_ops);
create index releases_title_trgm_idx on public.releases using gin (title extensions.gin_trgm_ops);

-- One physical barcode, one row: 012345678905 (UPC-A) and 0012345678905 (EAN-13) are the same product.
-- BEFORE triggers run before ON CONFLICT checks, so the conflict test sees the normalized value.
create function public.normalize_barcode() returns trigger
language plpgsql set search_path = '' as $$
begin
  if new.barcode is not null then
    new.barcode := regexp_replace(new.barcode, '[^0-9]', '', 'g');
    if new.barcode = '' then
      new.barcode := null;
    elsif length(new.barcode) = 12 then
      new.barcode := '0' || new.barcode;                 -- UPC-A -> EAN-13
    elsif length(new.barcode) = 14 and left(new.barcode, 1) = '0' then
      new.barcode := substr(new.barcode, 2);             -- GTIN-14 with leading 0 -> EAN-13
    end if;
  end if;
  return new;
end;
$$;
create trigger releases_normalize_barcode before insert or update of barcode on public.releases
  for each row execute function public.normalize_barcode();
create trigger releases_touch before update on public.releases
  for each row execute function public.touch_updated_at();

-- A box set is one release with several works.
create table public.release_works (
  release_id  uuid not null references public.releases (id) on delete cascade,
  work_id     uuid not null references public.works (id) on delete restrict,
  position    integer,                                   -- disc or volume order inside the release
  primary key (release_id, work_id)
);
create index release_works_work_idx on public.release_works (work_id);

-- The world's checklists ("every mainline Zelda game"); they power "what am I missing?".
create table public.sets (
  id           uuid primary key default gen_random_uuid(),
  name         text not null check (length(btrim(name)) > 0),
  description  text,
  created_by   uuid references auth.users (id) on delete set null,
  created_at   timestamptz not null default now()
);

create table public.set_members (
  set_id    uuid not null references public.sets (id) on delete cascade,
  work_id   uuid not null references public.works (id) on delete restrict,
  position  integer,
  primary key (set_id, work_id)
);
create index set_members_work_idx on public.set_members (work_id);

-- ============================================================
-- Private: people, occasions, items
-- ============================================================

create table public.people (
  id            uuid primary key default gen_random_uuid(),
  owner_id      uuid not null default auth.uid() references auth.users (id) on delete cascade,
  name          text not null check (length(btrim(name)) > 0),
  relationship  text,
  notes         text,
  created_at    timestamptz not null default now(),
  unique (owner_id, id)                                  -- target for same-owner composite FKs
);

create table public.occasions (
  id                   uuid primary key default gen_random_uuid(),
  owner_id             uuid not null default auth.uid() references auth.users (id) on delete cascade,
  name                 text not null check (length(btrim(name)) > 0),   -- "Christmas 2025", "Our wedding"
  kind                 text not null default 'other'
                         check (kind in ('holiday', 'birthday', 'wedding', 'sale', 'trip', 'purchase', 'other')),
  occurred_on          date,
  date_is_approximate  boolean not null default false,
  notes                text,
  created_at           timestamptz not null default now(),
  unique (owner_id, id)
);
create index occasions_owner_date_idx on public.occasions (owner_id, occurred_on desc);

create table public.items (
  id                   uuid primary key default gen_random_uuid(),
  owner_id             uuid not null default auth.uid() references auth.users (id) on delete cascade,
  name                 text not null check (length(btrim(name)) > 0),
  category_id          uuid not null references public.categories (id) on delete restrict,
  release_id           uuid references public.releases (id) on delete restrict,   -- null for unique things
  parent_item_id       uuid,                                                      -- containment
  occasion_id          uuid,
  giver_id             uuid,
  source               text,                       -- eBay, Target, yard sale, gift
  acquired_on          date,                       -- used when there is no occasion; the occasion's date wins
  date_is_approximate  boolean not null default false,
  condition_grade      text check (condition_grade in ('new', 'like_new', 'very_good', 'good', 'fair', 'poor')),
  sealed               boolean not null default false,
  intent               text not null default 'keep' check (intent in ('keep', 'maybe_sell', 'sell')),
  thank_you_sent       boolean not null default false,
  price_paid           numeric(10, 2) check (price_paid >= 0),
  location             text,
  notes                text,
  attributes           jsonb not null default '{}' check (jsonb_typeof(attributes) = 'object'),
  version              integer not null default 1,
  created_at           timestamptz not null default now(),
  updated_at           timestamptz not null default now(),
  unique (owner_id, id),
  check (parent_item_id <> id),
  -- Same-owner links. ON DELETE SET NULL (col) clears only the link column, not owner_id (Postgres 15+).
  foreign key (owner_id, parent_item_id) references public.items (owner_id, id) on delete set null (parent_item_id),
  foreign key (owner_id, occasion_id)    references public.occasions (owner_id, id) on delete set null (occasion_id),
  foreign key (owner_id, giver_id)       references public.people (owner_id, id) on delete set null (giver_id)
);
create index items_owner_category_idx on public.items (owner_id, category_id);
create index items_owner_created_idx  on public.items (owner_id, created_at desc, id desc);   -- keyset pagination
create index items_release_idx        on public.items (release_id) where release_id is not null;
create index items_parent_idx         on public.items (owner_id, parent_item_id) where parent_item_id is not null;
create index items_occasion_idx       on public.items (owner_id, occasion_id) where occasion_id is not null;
create index items_giver_idx          on public.items (owner_id, giver_id) where giver_id is not null;
-- jsonb_path_ops: smaller and faster than the default opclass for containment (attributes @> '{"brand":"Nintendo"}'),
-- which is the query the design needs; it gives up key-existence (?) operators.
create index items_attributes_idx     on public.items using gin (attributes jsonb_path_ops);
create index items_name_trgm_idx      on public.items using gin (name extensions.gin_trgm_ops);

create trigger items_bump_version before update on public.items
  for each row execute function public.bump_version();

-- ============================================================
-- Private: intake jobs and photos
-- ============================================================

create table public.intake_jobs (
  id            uuid primary key default gen_random_uuid(),
  owner_id      uuid not null default auth.uid() references auth.users (id) on delete cascade,
  status        text not null default 'queued'
                  check (status in ('queued', 'processing', 'needs_review', 'done', 'failed')),
  barcode       text,                              -- read in the browser, if any
  occasion_id   uuid,                              -- batch intake: "these are all from Christmas 2025"
  card          jsonb,                             -- the model's schema-checked proposal
  item_id       uuid,                              -- the item saved after confirmation
  error         text,
  attempts      integer not null default 0,
  max_attempts  integer not null default 3,
  run_after     timestamptz not null default now(),   -- retry backoff
  locked_by     text,
  locked_at     timestamptz,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),
  unique (owner_id, id),
  foreign key (owner_id, occasion_id) references public.occasions (owner_id, id) on delete set null (occasion_id),
  foreign key (owner_id, item_id)     references public.items (owner_id, id) on delete set null (item_id)
);
create index intake_jobs_claim_idx on public.intake_jobs (run_after, created_at) where status in ('queued', 'processing');
create index intake_jobs_owner_idx on public.intake_jobs (owner_id, created_at desc);
create trigger intake_jobs_touch before update on public.intake_jobs
  for each row execute function public.touch_updated_at();

create table public.photos (
  id             uuid primary key default gen_random_uuid(),
  owner_id       uuid not null default auth.uid() references auth.users (id) on delete cascade,
  item_id        uuid,                             -- null while the photo is still in intake
  intake_job_id  uuid,
  -- Storage paths are prefixed by the owner's id, as the storage policies will expect.
  storage_path   text not null unique check (storage_path like owner_id::text || '/%'),
  taken_at       timestamptz,                      -- the only metadata kept; suggests an occasion
  width          integer check (width > 0),
  height         integer check (height > 0),
  position       integer not null default 0,
  created_at     timestamptz not null default now(),
  foreign key (owner_id, item_id)       references public.items (owner_id, id) on delete cascade,
  foreign key (owner_id, intake_job_id) references public.intake_jobs (owner_id, id) on delete set null (intake_job_id)
);
create index photos_item_idx   on public.photos (owner_id, item_id, position) where item_id is not null;
create index photos_intake_idx on public.photos (owner_id, intake_job_id) where intake_job_id is not null;

-- ============================================================
-- Private: collections and wishlist
-- ============================================================

create table public.collections (
  id           uuid primary key default gen_random_uuid(),
  owner_id     uuid not null default auth.uid() references auth.users (id) on delete cascade,
  name         text not null check (length(btrim(name)) > 0),
  description  text,
  -- Null = not shared. Set it with new_share_token(); clearing it revokes the link.
  share_token  text unique check (length(share_token) >= 22),
  created_at   timestamptz not null default now(),
  unique (owner_id, id)
);

create table public.collection_items (
  collection_id  uuid not null,
  item_id        uuid not null,
  owner_id       uuid not null default auth.uid() references auth.users (id) on delete cascade,
  position       integer,
  added_at       timestamptz not null default now(),
  primary key (collection_id, item_id),
  foreign key (owner_id, collection_id) references public.collections (owner_id, id) on delete cascade,
  foreign key (owner_id, item_id)       references public.items (owner_id, id) on delete cascade
);
create index collection_items_item_idx on public.collection_items (owner_id, item_id);

create table public.wishlist (
  id          uuid primary key default gen_random_uuid(),
  owner_id    uuid not null default auth.uid() references auth.users (id) on delete cascade,
  release_id  uuid references public.releases (id) on delete set null,   -- "this exact steelbook"
  work_id     uuid references public.works (id) on delete set null,      -- "any copy of this"
  name        text,                                                      -- free text when neither exists
  priority    smallint not null default 0,
  max_price   numeric(10, 2) check (max_price >= 0),
  url         text,
  notes       text,
  created_at  timestamptz not null default now(),
  check (release_id is not null or work_id is not null or name is not null)
);
create index wishlist_owner_idx on public.wishlist (owner_id, priority desc);

-- ============================================================
-- Backend only: catalog cache (in the ERD; keeps free-tier lookups like UPC's ~100/day from running out)
-- ============================================================

create table public.catalog_cache (
  key         text primary key,                    -- "upc:0786936...", "tmdb_movie:search:princess mononoke"
  response    jsonb not null,
  fetched_at  timestamptz not null default now(),
  expires_at  timestamptz not null
);
create index catalog_cache_expires_idx on public.catalog_cache (expires_at);

-- ============================================================
-- Row-level security
-- ============================================================

alter table public.categories       enable row level security;
alter table public.works            enable row level security;
alter table public.releases         enable row level security;
alter table public.release_works    enable row level security;
alter table public.sets             enable row level security;
alter table public.set_members      enable row level security;
alter table public.people           enable row level security;
alter table public.occasions        enable row level security;
alter table public.items            enable row level security;
alter table public.intake_jobs      enable row level security;
alter table public.photos           enable row level security;
alter table public.collections      enable row level security;
alter table public.collection_items enable row level security;
alter table public.wishlist         enable row level security;
alter table public.catalog_cache    enable row level security;   -- no policies: service role only

-- Shared catalog: any signed-in user reads; no write policy exists, so only the service role writes.
create policy works_read         on public.works         for select to authenticated using (true);
create policy releases_read      on public.releases      for select to authenticated using (true);
create policy release_works_read on public.release_works for select to authenticated using (true);
create policy sets_read          on public.sets          for select to authenticated using (true);
create policy set_members_read   on public.set_members   for select to authenticated using (true);

-- Categories: built-ins are shared (service role writes them); users may add and edit their own.
create policy categories_read on public.categories for select to authenticated
  using (owner_id is null or owner_id = (select auth.uid()));
create policy categories_insert on public.categories for insert to authenticated
  with check (owner_id = (select auth.uid()));
create policy categories_update on public.categories for update to authenticated
  using (owner_id = (select auth.uid())) with check (owner_id = (select auth.uid()));
create policy categories_delete on public.categories for delete to authenticated
  using (owner_id = (select auth.uid()));

-- Private tables: owner only, every operation.
create policy people_owner on public.people for all to authenticated
  using (owner_id = (select auth.uid())) with check (owner_id = (select auth.uid()));
create policy occasions_owner on public.occasions for all to authenticated
  using (owner_id = (select auth.uid())) with check (owner_id = (select auth.uid()));
create policy photos_owner on public.photos for all to authenticated
  using (owner_id = (select auth.uid())) with check (owner_id = (select auth.uid()));
create policy collections_owner on public.collections for all to authenticated
  using (owner_id = (select auth.uid())) with check (owner_id = (select auth.uid()));
create policy collection_items_owner on public.collection_items for all to authenticated
  using (owner_id = (select auth.uid())) with check (owner_id = (select auth.uid()));
create policy wishlist_owner on public.wishlist for all to authenticated
  using (owner_id = (select auth.uid())) with check (owner_id = (select auth.uid()));
-- Items may only use a built-in category or one of the owner's own.
create policy items_owner on public.items for all to authenticated
  using (owner_id = (select auth.uid()))
  with check (
    owner_id = (select auth.uid())
    and exists (select 1 from public.categories c
                where c.id = items.category_id and (c.owner_id is null or c.owner_id = (select auth.uid())))
  );
-- Intake jobs: owners read theirs. The API creates them (after its per-user rate limit) and workers update
-- them, both with the service role; a direct insert would skip the limit and spend AI money.
create policy intake_jobs_owner_read on public.intake_jobs for select to authenticated
  using (owner_id = (select auth.uid()));

-- Grants. Supabase grants everything on new public tables to anon and authenticated by default;
-- RLS already blocks them, and these revokes make the boundary hold even if a policy is added by mistake.
revoke all on public.categories, public.works, public.releases, public.release_works, public.sets,
  public.set_members, public.people, public.occasions, public.items, public.intake_jobs, public.photos,
  public.collections, public.collection_items, public.wishlist, public.catalog_cache from anon;
revoke insert, update, delete, truncate on public.works, public.releases, public.release_works,
  public.sets, public.set_members from authenticated;
revoke insert, update, delete, truncate on public.intake_jobs from authenticated;
revoke all on public.catalog_cache from authenticated;

-- ============================================================
-- Job queue: claim_intake_job()
-- ============================================================

-- Claims the oldest runnable job for one worker, or returns no row. FOR UPDATE SKIP LOCKED makes
-- concurrent workers step over rows another transaction has locked instead of waiting for them, so two
-- workers never get the same job. A job stuck in 'processing' past the lease (a crashed worker) is reclaimable.
create function public.claim_intake_job(p_worker text, p_lease interval default interval '5 minutes')
returns setof public.intake_jobs
language sql volatile set search_path = '' as $$
  with next_job as (
    select id
    from public.intake_jobs
    where run_after <= now()
      and attempts < max_attempts
      and (status = 'queued' or (status = 'processing' and locked_at < now() - p_lease))
    order by run_after, created_at
    limit 1
    for update skip locked
  )
  update public.intake_jobs j
  set status = 'processing', locked_by = p_worker, locked_at = now(), attempts = j.attempts + 1
  from next_job
  where j.id = next_job.id
  returning j.*;
$$;
revoke execute on function public.claim_intake_job(text, interval) from public, anon, authenticated;
grant execute on function public.claim_intake_job(text, interval) to service_role;

-- ============================================================
-- Collection sharing
-- ============================================================

-- 18 random bytes = 144 bits, URL-safe base64 (24 characters).
create function public.new_share_token() returns text
language sql volatile set search_path = '' as $$
  select translate(encode(extensions.gen_random_bytes(18), 'base64'), '+/', '-_');
$$;

-- The only way anon reads private data: a shared collection by its token, with chosen fields only.
-- Never price_paid, location, notes, giver, or occasion.
create function public.get_shared_collection(p_token text)
returns table (collection_name text, item_id uuid, item_name text, category text,
               release_title text, edition text, format text, condition_grade text, sealed boolean)
language sql stable security definer set search_path = '' as $$
  select c.name, i.id, i.name, cat.name, r.title, r.edition, r.format, i.condition_grade, i.sealed
  from public.collections c
  join public.collection_items ci on ci.collection_id = c.id
  join public.items i on i.id = ci.item_id
  join public.categories cat on cat.id = i.category_id
  left join public.releases r on r.id = i.release_id
  where p_token is not null and c.share_token = p_token
  order by ci.position nulls last, i.name;
$$;
revoke execute on function public.get_shared_collection(text) from public;
grant execute on function public.get_shared_collection(text) to anon, authenticated;
