-- The Bento Registry: who publishes, from which machine, and what.
--
-- Reading is open to anyone (the anon/publishable key). Every write that matters
-- goes through the `publish` edge function, which runs with the service role and
-- checks the machine's signature first. The only things a signed-in person writes
-- directly are their own profile, their own machines and a report.

create extension if not exists pgcrypto;

-- A person's public face. The email stays in auth.users and is never exposed.
create table public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  handle text unique not null check (handle ~ '^[a-z0-9][a-z0-9-]{1,30}[a-z0-9]$'),
  created_at timestamptz not null default now()
);

-- A Bento that may publish. Its private key never leaves the machine; this row
-- holds the public half, so a signature names exactly one registered machine.
create table public.machines (
  id uuid primary key default gen_random_uuid(),
  owner uuid not null references auth.users(id) on delete cascade,
  name text not null check (length(name) between 1 and 60),
  key_id text unique not null check (key_id ~ '^bm-[0-9a-f]{16}$'),
  public_key text not null check (length(public_key) = 44),
  version text not null default '' check (length(version) <= 40),
  created_at timestamptz not null default now(),
  last_seen timestamptz,
  revoked_at timestamptz
);
create index machines_owner on public.machines(owner);

create table public.listings (
  id uuid primary key default gen_random_uuid(),
  kind text not null check (kind in ('app','agent','skill','soul','tool')),
  slug text not null check (slug ~ '^[a-z0-9][a-z0-9-]{0,62}[a-z0-9]$'),
  owner uuid not null references auth.users(id) on delete cascade,
  name text not null check (length(name) between 1 and 80),
  summary text not null default '' check (length(summary) <= 280),
  icon text not null default '' check (length(icon) <= 8),
  downloads bigint not null default 0,
  hidden boolean not null default false,
  hidden_why text not null default '',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (kind, slug)
);

create table public.versions (
  id uuid primary key default gen_random_uuid(),
  listing_id uuid not null references public.listings(id) on delete cascade,
  version text not null check (version ~ '^[0-9]{1,6}(\.[0-9]{1,6}){0,2}$'),
  notes text not null default '' check (length(notes) <= 2000),
  path text not null,
  sha256 text not null check (sha256 ~ '^[0-9a-f]{64}$'),
  size integer not null check (size > 0 and size <= 2097152),
  key_id text not null references public.machines(key_id),
  signature text not null,
  report jsonb not null default '{}'::jsonb,
  permissions text[] not null default '{}',
  downloads bigint not null default 0,
  yanked boolean not null default false,
  created_at timestamptz not null default now(),
  unique (listing_id, version)
);
create index versions_listing on public.versions(listing_id, created_at desc);

-- One counted download per address per version per day. Only a hash of the
-- address is kept, salted per day so it can't be reversed by a lookup table.
create table public.download_marks (
  version_id uuid not null references public.versions(id) on delete cascade,
  who text not null,
  day date not null default current_date,
  primary key (version_id, who, day)
);

create table public.reports (
  id uuid primary key default gen_random_uuid(),
  listing_id uuid not null references public.listings(id) on delete cascade,
  reporter uuid not null references auth.users(id) on delete cascade,
  reason text not null check (length(reason) between 3 and 1000),
  created_at timestamptz not null default now(),
  unique (listing_id, reporter)
);

create table public.admins (
  id uuid primary key references auth.users(id) on delete cascade
);

-- Publishing is metered so a stolen session can't flood the registry.
create table public.publish_log (
  owner uuid not null,
  at timestamptz not null default now()
);
create index publish_log_owner on public.publish_log(owner, at desc);

-- ---------------------------------------------------------------------------
-- Row-level security
-- ---------------------------------------------------------------------------
alter table public.profiles enable row level security;
alter table public.machines enable row level security;
alter table public.listings enable row level security;
alter table public.versions enable row level security;
alter table public.download_marks enable row level security;
alter table public.reports enable row level security;
alter table public.admins enable row level security;
alter table public.publish_log enable row level security;

create or replace function public.is_admin() returns boolean
language sql stable security definer set search_path = public as
$$ select exists (select 1 from public.admins where id = auth.uid()) $$;

create policy "profiles are public" on public.profiles for select using (true);
create policy "own profile insert" on public.profiles for insert to authenticated
  with check (id = (select auth.uid()));
create policy "own profile update" on public.profiles for update to authenticated
  using (id = (select auth.uid())) with check (id = (select auth.uid()));

create policy "own machines" on public.machines for select to authenticated
  using (owner = (select auth.uid()));
create policy "register own machine" on public.machines for insert to authenticated
  with check (owner = (select auth.uid()) and revoked_at is null);
-- Revoking is the only change a person makes to a machine row.
create policy "revoke own machine" on public.machines for update to authenticated
  using (owner = (select auth.uid())) with check (owner = (select auth.uid()));

create policy "listings are public" on public.listings for select
  using (not hidden or owner = (select auth.uid()) or (select public.is_admin()));
create policy "admins moderate" on public.listings for update to authenticated
  using ((select public.is_admin())) with check ((select public.is_admin()));

create policy "versions are public" on public.versions for select
  using (exists (select 1 from public.listings l where l.id = listing_id
                 and (not l.hidden or l.owner = (select auth.uid()) or (select public.is_admin()))));

create policy "report once" on public.reports for insert to authenticated
  with check (reporter = (select auth.uid()));
create policy "see own reports" on public.reports for select to authenticated
  using (reporter = (select auth.uid()) or (select public.is_admin()));

create policy "admins see admins" on public.admins for select to authenticated
  using ((select public.is_admin()));
-- download_marks and publish_log: no policies, so only the service role reads them.

-- The column-level part of "revoking is the only change": a person can't move
-- a machine to another account or swap its key after it signed things.
revoke update on public.machines from authenticated;
grant update (revoked_at, name, version, last_seen) on public.machines to authenticated;
revoke update on public.listings from authenticated;
grant update (hidden, hidden_why) on public.listings to authenticated;

-- ---------------------------------------------------------------------------
-- Guards that hold whatever door a row came through
-- ---------------------------------------------------------------------------
create or replace function public.machine_limits() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  if tg_op = 'INSERT' then
    if (select count(*) from public.machines where owner = new.owner and revoked_at is null) >= 10 then
      raise exception 'an account can register at most 10 machines; revoke one first';
    end if;
  elsif tg_op = 'UPDATE' then
    if old.revoked_at is not null and new.revoked_at is null then
      raise exception 'a revoked machine stays revoked; register it again';
    end if;
  end if;
  return new;
end $$;
create trigger machines_limits before insert or update on public.machines
  for each row execute function public.machine_limits();

-- Three people reporting a listing takes it off the site until an admin looks.
create or replace function public.report_hides() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  if (select count(*) from public.reports where listing_id = new.listing_id) >= 3 then
    update public.listings set hidden = true, hidden_why = 'reported'
     where id = new.listing_id and not hidden;
  end if;
  return new;
end $$;
create trigger reports_hide after insert on public.reports
  for each row execute function public.report_hides();

-- Version strings compare as numbers: 1.10 is after 1.9.
create or replace function public.version_key(v text) returns int[]
language sql immutable as
$$ select array_agg(x::int order by n) from unnest(string_to_array(v, '.')) with ordinality as t(x, n) $$;

-- ---------------------------------------------------------------------------
-- What the site and every Bento read
-- ---------------------------------------------------------------------------
create or replace view public.catalog with (security_invoker = true) as
select l.id, l.kind, l.slug, l.name, l.summary, l.icon, l.downloads,
       l.created_at, l.updated_at, p.handle as publisher,
       v.version as latest, v.id as latest_id, v.report->>'verdict' as verdict,
       v.permissions, (select count(*) from public.versions x
                       where x.listing_id = l.id and not x.yanked) as version_count
  from public.listings l
  join public.profiles p on p.id = l.owner
  left join lateral (select * from public.versions x where x.listing_id = l.id and not x.yanked
                     order by public.version_key(x.version) desc limit 1) v on true
 where not l.hidden;

-- A publisher's public key, so an installing Bento can check the signature itself.
create or replace function public.publisher_key(kid text)
returns table (key_id text, public_key text, revoked boolean, handle text)
language sql stable security definer set search_path = public as $$
  select m.key_id, m.public_key, m.revoked_at is not null, p.handle
    from public.machines m join public.profiles p on p.id = m.owner
   where m.key_id = kid
$$;
grant execute on function public.publisher_key(text) to anon, authenticated;

grant select on public.catalog to anon, authenticated;

-- The package files. Public to read; only the publish function writes.
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('packages', 'packages', true, 2097152, array['application/json'])
on conflict (id) do nothing;
