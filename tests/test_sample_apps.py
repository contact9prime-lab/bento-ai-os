"""Bento's own sample apps (agentos/sampleapps), packaged for the Bento Registry.

They are ordinary app packages: held to App Studio's bar, clean on the publish report,
valid for the registry's checks, and installed through the Import door like any app.
The live run (packaging/dev/sample-apps-e2e/run.py) uses each one in a browser.
"""
import json
import re
from pathlib import Path

import pytest

from agentos import appcheck, appregistry, registryhub as hub, sampleapps

SLUGS = [a["slug"] for a in sampleapps.APPS]
ROOT = Path(__file__).resolve().parent.parent


def test_the_checked_in_packages_are_built_from_the_sources():
    assert sampleapps.stale() == [], "run: bento studio samples build"


def test_every_sample_has_a_package_its_source_and_a_line_for_the_registry():
    assert len(SLUGS) == len(set(SLUGS)) >= 5
    for a in sampleapps.APPS:
        assert (sampleapps.HERE / f"{a['slug']}.html").is_file()
        assert sampleapps.path_of(a["slug"]).is_file()
        assert 0 < len(a["summary"]) <= 280 and "—" not in a["summary"] and "—" not in a["about"]
        assert hub.slug_of(a["name"]) == a["slug"], "the registry address is made from the name"


@pytest.mark.parametrize("slug", SLUGS)
def test_each_app_meets_app_studios_bar(slug):
    html = sampleapps.html_of(slug)
    issues = appcheck.check(html).issues
    assert issues == [], [(i.level, i.code, i.message) for i in issues]
    # the parts the bar asks for by name
    for must in ("widget-only", "desktop-only", "appData.set", "appLLM.stream", "appCopilot.mount",
                 "appConfirm", "appToast", 'class="empty', "appShare"):
        assert must in html, f"{slug} has no {must}"
    assert re.search(r"[Tt]ry (it with )?an example", html), "a first run offers example data"
    # the assistant sits on the desktop surface only: on a widget it covers the one fact
    assert "if(appSurface.desktop) appCopilot.mount" in html
    assert not re.search(r"(?<![\w.])(confirm|prompt)\(", html)
    assert "localStorage" not in html
    assert "http://" not in html and "https://" not in html, "an app frame loads nothing from outside"


@pytest.mark.parametrize("slug", SLUGS)
def test_each_package_is_clean_on_the_publish_report_and_valid_for_the_registry(slug):
    pkg = json.loads(sampleapps.path_of(slug).read_text())
    rep = hub.report("app", hub.text_of(pkg), pkg)
    assert rep["verdict"] == "pass" and rep["blocking"] == [] and rep["warnings"] == [], rep
    man = pkg["manifest"]
    assert pkg["format"] == appregistry.PACKAGE_FORMAT
    assert appregistry.verify_package(pkg)[0] == "unsigned"         # checksum holds; nobody signed it
    assert appregistry.author_problem(man) == "" and man["author"]["kind"] == "agent"
    assert appregistry.scan_drift(man, pkg["html"]) == ""
    assert man["security"]["verdict"] == "pass"
    for p in man["permissions"]:
        assert p["reason"] and p["action"] and p["resource"]


@pytest.mark.parametrize("slug", SLUGS)
def test_each_app_declares_everything_its_source_asks_for(slug):
    from agentos import server
    html = sampleapps.html_of(slug)
    want = {(p["action"], p["resource"]) for p in server._scan_app_permissions(html)}
    have = {(p["action"], p["resource"]) for p in sampleapps.BY_SLUG[slug]["permissions"]}
    # the scanner says app.data.* for "uses its data"; the package says read and write apart
    if ("app.data.*", "app:self/data") in want:
        want.discard(("app.data.*", "app:self/data"))
    assert want <= have, want - have
    assert {("app.data.read", "app:self/data"), ("app.data.write", "app:self/data")} <= have


def test_the_registry_validator_and_index_take_them():
    import subprocess
    import sys
    r = subprocess.run([sys.executable, str(ROOT / "registry/scripts/validate.py")], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    index = json.loads((ROOT / "registry/index.json").read_text())
    assert {a["id"] for a in index["apps"]} >= set(SLUGS), "run registry/scripts/build_index.py"


def test_a_sample_installs_through_the_import_door_with_its_grants():
    from fastapi.testclient import TestClient
    from agentos import server as servermod
    pkg = json.loads(sampleapps.path_of("habit-tracker").read_text())
    with TestClient(servermod.app, base_url="http://127.0.0.1") as c:
        st = c.post("/api/apps/import", json={"package": pkg}).json()
        assert st["security"] == "pass" and st["signature_status"] == "unsigned" and st["author_kind"] == "agent"
        done = c.post(f"/api/apps/import/{st['install_id']}/confirm", json={}).json()
        aid = done["id"]
        try:
            grants = {(g["action"], g["resource"]) for g in servermod.state["store"].list_grants()
                      if g.get("principal_id") == aid}
            assert ("app.data.write", f"app:{aid}/data") in grants
            assert ("tool.use", "tool:llm_generate*") in grants
            page = c.get(f"/api/apps/{aid}/page").text
            assert "Habit Tracker" in page and "appCopilot.mount" in page
        finally:
            servermod.state["store"].delete_app(aid)


def test_pushing_a_sample_without_a_summary_uses_its_own_line():
    from agentos.__main__ import _app_summary
    pkg = json.loads(sampleapps.path_of("kanban-board").read_text())
    assert _app_summary(pkg) == sampleapps.BY_SLUG["kanban-board"]["summary"]
    other = {"manifest": {"name": "Mine", "description": "Counts things. And more."}, "html": "<p>x</p>"}
    assert _app_summary(other) == "Counts things"


def test_a_scan_time_or_a_date_is_not_a_phone_number():
    for text, phone in (("call me on +44 7700 900123", True), ("(555) 123-4567", True), ("555-123-4567", True),
                        ('"scanned_at": 1795803404', False), ("due 2026-12-04", False), ("id 123456789012", False)):
        pkg = {"format": hub.KINDS["skill"], "name": "x", "content": text}
        seen = {w["what"] for w in hub.report("skill", hub.text_of(pkg), pkg)["warnings"]}
        assert ("a phone number" in seen) is phone, text


def test_bentos_reserved_names_match_the_registrys():
    sql = (ROOT / "packaging/registry-cloud/migrations/003_reserved_handles.sql").read_text()
    names = re.findall(r"'([a-z0-9-]+)'", sql.split("array[", 1)[1].split("]", 1)[0])
    assert tuple(names) == hub.RESERVED and hub.OFFICIAL in names
    assert all(hub.HANDLE.fullmatch(n) for n in names)
    # the trigger lets an admin take one, and nobody else
    assert "not public.is_admin()" in sql and "before insert or update of handle" in sql


def test_a_reserved_name_is_refused_in_words(monkeypatch):
    def refuse(*a, **k):
        raise hub.HubError('the publisher name bento is kept for Bento (P0001)', status=400)
    monkeypatch.setattr(hub, "_read_state", lambda: {"user_id": "u1"})
    monkeypatch.setattr(hub, "_token", lambda: "t")
    monkeypatch.setattr(hub, "_profile", lambda *a: None)
    monkeypatch.setattr(hub, "_call", refuse)
    with pytest.raises(hub.HubError, match="kept for Bento's own listings"):
        hub.set_handle("bento")


def test_the_store_marks_bentos_own_listings():
    js = (ROOT / "agentos/ui/src/js/25b-registry.js").read_text()
    assert "it.publisher==='bento'" in js and "Published by Bento" in js


def test_no_sample_shares_a_name_with_one_of_the_stores_own_apps():
    # importing one would offer to overwrite the person's installed app of that name
    from agentos import server
    taken = {t["name"].lower() for t in server.STORE_TEMPLATES}
    assert not taken & {a["name"].lower() for a in sampleapps.APPS}
