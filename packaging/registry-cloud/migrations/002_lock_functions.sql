-- Trigger functions aren't for calling; the download counter is the download
-- function's alone (service role).
revoke execute on function public.machine_limits() from public, anon, authenticated;
revoke execute on function public.report_hides() from public, anon, authenticated;
revoke execute on function public.version_key(text) from public, anon, authenticated;
grant execute on function public.version_key(text) to authenticated, anon;
create or replace function public.count_download(vid uuid, who text) returns boolean
language plpgsql security definer set search_path = public as $$
begin
  insert into public.download_marks(version_id, who) values (vid, who);
  update public.versions set downloads = downloads + 1 where id = vid;
  update public.listings set downloads = downloads + 1
   where id = (select listing_id from public.versions where id = vid);
  return true;
exception when unique_violation then
  return false;
end $$;
revoke execute on function public.count_download(uuid, text) from public, anon, authenticated;
grant execute on function public.count_download(uuid, text) to service_role;
create index download_marks_day on public.download_marks(day);
