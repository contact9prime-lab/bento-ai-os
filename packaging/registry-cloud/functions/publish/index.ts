// The Bento Registry's one write door.
//
// A Bento has already checked the package (security scan, leak scan, format)
// and shown its owner the report. This function checks again what it can check
// for itself, and above all that the bytes were signed by a machine registered
// to the account that is signed in. It runs with the service role, so nothing
// a person could send straight to the database can skip these checks.
import { createClient } from "jsr:@supabase/supabase-js@2";
import { LEAK_RULES } from "./leakrules.ts";

const URL_ = Deno.env.get("SUPABASE_URL")!;
const SERVICE = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
const admin = createClient(URL_, SERVICE, { auth: { persistSession: false } });

const KINDS: Record<string, string> = {
  app: "agentos-app/1",
  agent: "agentos-agent/1",
  skill: "bento-skill/1",
  soul: "bento-soul/1",
  tool: "bento-tool/1",
};
const MAX_BYTES = 2 * 1024 * 1024;
const PER_HOUR = 10;
const PER_DAY = 30;
const SLUG = /^[a-z0-9][a-z0-9-]{0,62}[a-z0-9]$/;
const VERSION = /^[0-9]{1,6}(\.[0-9]{1,6}){0,2}$/;

const cors = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, apikey, content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};

function no(status: number, why: string, extra: Record<string, unknown> = {}) {
  return new Response(JSON.stringify({ ok: false, error: why, ...extra }), {
    status, headers: { ...cors, "Content-Type": "application/json" },
  });
}

function b64(s: string): Uint8Array {
  return Uint8Array.from(atob(s), (c) => c.charCodeAt(0));
}

async function sha256hex(bytes: Uint8Array): Promise<string> {
  const d = new Uint8Array(await crypto.subtle.digest("SHA-256", bytes));
  return Array.from(d, (x) => x.toString(16).padStart(2, "0")).join("");
}

function vkey(v: string): number[] {
  return v.split(".").map((x) => parseInt(x, 10));
}

function newer(a: string, b: string): boolean {
  const x = vkey(a), y = vkey(b);
  for (let i = 0; i < Math.max(x.length, y.length); i++) {
    const p = x[i] ?? 0, q = y[i] ?? 0;
    if (p !== q) return p > q;
  }
  return false;
}

function leaks(text: string): string[] {
  const out: string[] = [];
  for (const [label, src, flags] of LEAK_RULES) {
    if (new RegExp(src, flags).test(text)) out.push(label);
  }
  return out;
}

function clip(v: unknown, n: number): string {
  return String(v ?? "").replace(/[\u0000-\u001f\u007f-\u009f‪-‮⁦-⁩]/g, " ").trim().slice(0, n);
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: cors });
  if (req.method !== "POST") return no(405, "POST only");

  const jwt = (req.headers.get("Authorization") || "").replace(/^Bearer\s+/i, "");
  if (!jwt) return no(401, "sign in to the Bento registry first");
  const { data: who, error: werr } = await admin.auth.getUser(jwt);
  if (werr || !who?.user) return no(401, "your registry session has ended; sign in again");
  const uid = who.user.id;

  const raw = await req.text();
  if (raw.length > MAX_BYTES * 2) return no(413, "the package is over 2 MB");
  let body: Record<string, unknown>;
  try { body = JSON.parse(raw); } catch { return no(400, "the request is not JSON"); }

  const kind = String(body.kind || "");
  const slug = String(body.slug || "");
  const version = String(body.version || "");
  const pkgText = String(body.package || "");
  const keyId = String(body.key_id || "");
  const signature = String(body.signature || "");
  if (!(kind in KINDS)) return no(400, `kind must be one of ${Object.keys(KINDS).join(", ")}`);
  if (!SLUG.test(slug)) return no(400, "the name for the address must be lower case letters, digits and dashes");
  if (!VERSION.test(version)) return no(400, "a version is numbers with dots, like 1.2.0");

  const bytes = new TextEncoder().encode(pkgText);
  if (!bytes.length || bytes.length > MAX_BYTES) return no(413, "the package is empty or over 2 MB");

  // Who may publish: a handle, and a machine of theirs that isn't revoked.
  const { data: prof } = await admin.from("profiles").select("handle").eq("id", uid).maybeSingle();
  if (!prof) return no(403, "choose a publisher name first");
  const { data: mach } = await admin.from("machines").select("public_key, revoked_at, owner")
    .eq("key_id", keyId).maybeSingle();
  if (!mach || mach.owner !== uid) return no(403, "this machine isn't registered to your account");
  if (mach.revoked_at) return no(403, "this machine was revoked; register it again");

  // The signature is over the exact bytes that will be stored.
  const hex = await sha256hex(bytes);
  try {
    const pub = await crypto.subtle.importKey("raw", b64(mach.public_key), { name: "Ed25519" }, false, ["verify"]);
    const ok = await crypto.subtle.verify("Ed25519", pub, b64(signature), new TextEncoder().encode("sha256:" + hex));
    if (!ok) return no(400, "the signature doesn't match the package");
  } catch {
    return no(400, "the signature couldn't be read");
  }

  // The package is what it says it is, and carries nothing key-shaped.
  let pkg: Record<string, unknown>;
  try { pkg = JSON.parse(pkgText); } catch { return no(400, "the package is not JSON"); }
  if (pkg.format !== KINDS[kind]) {
    return no(400, `that isn't ${kind === "app" || kind === "agent" ? "an" : "a"} ${kind} package (its format should be ${KINDS[kind]})`);
  }
  const found = leaks(pkgText);
  if (found.length) return no(422, "the package contains something that looks like a credential", { leaks: found });

  // Metered, so a stolen session can't flood the registry.
  const hour = new Date(Date.now() - 3600e3).toISOString();
  const day = new Date(Date.now() - 86400e3).toISOString();
  const { count: inHour } = await admin.from("publish_log").select("*", { count: "exact", head: true })
    .eq("owner", uid).gte("at", hour);
  const { count: inDay } = await admin.from("publish_log").select("*", { count: "exact", head: true })
    .eq("owner", uid).gte("at", day);
  if ((inHour ?? 0) >= PER_HOUR || (inDay ?? 0) >= PER_DAY) {
    return no(429, `you can publish ${PER_HOUR} times an hour and ${PER_DAY} a day; try again later`);
  }

  // The address belongs to whoever published it first.
  const name = clip(body.name, 80) || slug;
  const summary = clip(body.summary, 280);
  const icon = clip(body.icon, 8);
  let { data: listing } = await admin.from("listings").select("id, owner, hidden, hidden_why")
    .eq("kind", kind).eq("slug", slug).maybeSingle();
  if (listing && listing.owner !== uid) return no(409, `${kind}/${slug} belongs to another publisher; choose another name`);
  if (listing?.hidden && listing.hidden_why === "reported") {
    return no(423, "this listing is held after reports; it needs a look from the registry first");
  }

  if (listing) {
    const { data: prev } = await admin.from("versions").select("version").eq("listing_id", listing.id);
    for (const p of prev || []) {
      if (!newer(version, p.version)) {
        return no(409, `version ${version} isn't newer than ${p.version}, which is already published`);
      }
    }
  }

  const path = `${kind}/${slug}/${version}.json`;
  const up = await admin.storage.from("packages").upload(path, bytes, {
    contentType: "application/json", upsert: false,
  });
  if (up.error) return no(500, "the package couldn't be stored: " + up.error.message);

  if (!listing) {
    const ins = await admin.from("listings").insert({ kind, slug, owner: uid, name, summary, icon })
      .select("id, owner, hidden, hidden_why").single();
    if (ins.error) {
      await admin.storage.from("packages").remove([path]);
      return no(409, "that name was just taken; choose another");
    }
    listing = ins.data;
  } else {
    await admin.from("listings").update({ name, summary, icon, updated_at: new Date().toISOString() })
      .eq("id", listing.id);
  }

  const report = (typeof body.report === "object" && body.report) ? body.report as Record<string, unknown> : {};
  const perms = Array.isArray(body.permissions) ? (body.permissions as unknown[]).map((p) => clip(p, 120)).slice(0, 60) : [];
  const ver = await admin.from("versions").insert({
    listing_id: listing!.id, version, notes: clip(body.notes, 2000), path, sha256: hex,
    size: bytes.length, key_id: keyId, signature,
    report: { ...report, server: { leaks: [], format: KINDS[kind], checked_at: new Date().toISOString() } },
    permissions: perms,
  }).select("id").single();
  if (ver.error) {
    await admin.storage.from("packages").remove([path]);
    return no(500, "the version couldn't be recorded: " + ver.error.message);
  }
  await admin.from("publish_log").insert({ owner: uid });
  await admin.from("machines").update({ last_seen: new Date().toISOString() }).eq("key_id", keyId);

  return new Response(JSON.stringify({
    ok: true, kind, slug, version, id: ver.data.id, sha256: hex, publisher: prof.handle,
    page: `https://bentoboxos.com/registry/#${kind}/${slug}`,
  }), { headers: { ...cors, "Content-Type": "application/json" } });
});
