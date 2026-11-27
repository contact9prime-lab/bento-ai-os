-- Publisher names that read as Bento itself are kept for the registry's admins, so a
-- listing by "bento" is Bento's own. The list is registryhub.RESERVED too, and
-- tests/test_sample_apps.py fails when the two differ.
--
-- A name taken before this ran stays where it is: look for one with
--   select id, handle from public.profiles where public.reserved_handle(handle);
create or replace function public.reserved_handle(h text) returns boolean
language sql immutable set search_path = public as
$$ select h = any (array['bento', 'bentobox', 'bentoboxos', 'bento-ai', 'bentoai', 'bento-os',
                         'bento-team', 'official', 'registry', 'admin', 'support']) $$;

create or replace function public.keep_reserved() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  if public.reserved_handle(new.handle) and not public.is_admin()
     and (tg_op = 'INSERT' or old.handle is distinct from new.handle) then
    raise exception 'the publisher name % is kept for Bento', new.handle using errcode = 'P0001';
  end if;
  return new;
end $$;

create trigger profiles_reserved before insert or update of handle on public.profiles
  for each row execute function public.keep_reserved();
revoke execute on function public.keep_reserved() from public, anon, authenticated;
