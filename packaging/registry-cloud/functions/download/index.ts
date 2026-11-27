// Where a package is fetched from, so a download is counted once per address
// per version per day. Only a salted hash of the address is kept, for a day.
//
//   GET ?kind=app&slug=notes[&version=1.2]   → JSON: where the file is and how to check it
//   ... &go=1                                → a redirect to the file (the site's button)
import { createClient } from "jsr:@supabase/supabase-js@2";

const URL_ = Deno.env.get("SUPABASE_URL")!;
const SERVICE = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
const admin = createClient(URL_, SERVICE, { auth: { persistSession: false } });
const cors = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, apikey, content-type",
  "Access-Control-Allow-Methods": "GET, OPTIONS",
};
const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { ...cors, "Content-Type": "application/json" } });

async function hash(s: string): Promise<string> {
  const d = new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s)));
  return Array.from(d, (x) => x.toString(16).padStart(2, "0")).join("").slice(0, 32);
}

function vkey(v: string): number[] { return v.split(".").map((x) => parseInt(x, 10)); }
function cmp(a: string, b: string): number {
  const x = vkey(a), y = vkey(b);
  for (let i = 0; i < Math.max(x.length, y.length); i++) {
    const d = (x[i] ?? 0) - (y[i] ?? 0);
    if (d) return d;
  }
  return 0;
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: cors });
  const q = new URL(req.url).searchParams;
  const kind = q.get("kind") || "", slug = q.get("slug") || "", want = q.get("version") || "";

  const { data: l } = await admin.from("listings").select("id, name, hidden, owner")
    .eq("kind", kind).eq("slug", slug).maybeSingle();
  if (!l || l.hidden) return json(404, { ok: false, error: `nothing called ${kind}/${slug} in the registry` });
  const { data: vs } = await admin.from("versions")
    .select("id, version, path, sha256, size, key_id, signature, report, permissions, notes, yanked, created_at")
    .eq("listing_id", l.id);
  const live = (vs || []).filter((v) => !v.yanked).sort((a, b) => cmp(b.version, a.version));
  const v = want ? live.find((x) => x.version === want) : live[0];
  if (!v) return json(404, { ok: false, error: want ? `version ${want} isn't published` : "no version is published" });

  const ip = (req.headers.get("x-forwarded-for") || "").split(",")[0].trim() || "unknown";
  const day = new Date().toISOString().slice(0, 10);
  await admin.rpc("count_download", { vid: v.id, who: await hash(`${SERVICE}|${day}|${ip}`) });

  const file = `${URL_}/storage/v1/object/public/packages/${v.path}`;
  if (q.get("go")) return Response.redirect(file, 302);
  const { data: pk } = await admin.rpc("publisher_key", { kid: v.key_id });
  return json(200, {
    ok: true, kind, slug, name: l.name, version: v.version, url: file, sha256: v.sha256, size: v.size,
    key_id: v.key_id, signature: v.signature, publisher_key: pk?.[0]?.public_key || "",
    publisher: pk?.[0]?.handle || "", revoked: !!pk?.[0]?.revoked, report: v.report,
    permissions: v.permissions, notes: v.notes, published: v.created_at,
  });
});
