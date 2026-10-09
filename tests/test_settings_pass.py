"""Settings, looked at tab by tab and fixed.

Asked for as "there are still so many issues in the settings like look and feel and
better organization of things". Every tab was photographed at 1440x900 and on a 390px
phone first. What that found, and what these pin:

- one Save at the foot of every tab covered only some of what was on it, so some
  things applied at once, others waited for Save, and a name typed and left for
  another tab was lost. Fields now save themselves.
- every switched-off cloud provider was a whole card of empty fields;
- Agents and Team were each one long group, Accounts opened on GitHub, Channels opened
  on five built-in cards nobody fills in, and speech to text sat under Appearance;
- text painted straight into a card ran into its edge, and a named card's heading was
  a 2xs grey label in the immersive look.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

JS = ROOT / "agentos/ui/src/js"
CSS = ROOT / "agentos/ui/src/css"
SETTINGS = (JS / "11-settings.js").read_text()


def _tab(name: str) -> str:
    i = SETTINGS.index(f"if(want('{name}')){{")
    j = SETTINGS.find("if(want('", i + 10)
    return SETTINGS[i:j]


def _groups(src: str) -> list[str]:
    return re.findall(r"pGroup\('([^']*)'", src) + re.findall(r'<h3>([^<$]+)</h3>', src)


def test_there_is_no_page_wide_save_and_every_field_it_read_saves_itself():
    assert "savebar" not in SETTINGS
    assert "savebar" not in (CSS / "14-omnibar.css").read_text()
    body = SETTINGS[SETTINGS.index("async function saveSettings"):SETTINGS.index("function setAutoSave")]
    ids = set(re.findall(r"(?:val|on|el|list)\('([\w-]+)'\)", body))
    ids |= set(re.findall(r"getElementById\('([\w-]+)'\)", body))
    ids -= {"s-upd-src"}
    auto = re.search(r"var SET_AUTO=/(.+)/;", SETTINGS).group(1)
    rx = re.compile(auto.replace("\\/", "/"))
    missed = sorted(i for i in ids if not rx.search(i))
    assert not missed, f"saveSettings reads these but they never save themselves: {missed}"
    assert "pm.addEventListener('change'" in SETTINGS and "setAutoSave(e)" in SETTINGS
    assert 'id="set-saved"' in SETTINGS


def test_a_switched_off_provider_is_one_row():
    ai = _tab("ai")
    assert ai.count("fold:true") >= 2          # the cloud providers and the custom server
    assert "cls:'pmore'" in ai and "cls:'phead-row'" in ai
    css = (CSS / "11-prefs.css").read_text()
    assert ".pgroup.pfold:not(.open) > .prow.pmore{display:none}" in css
    # searching shows every field, folded or not
    assert ".prefs-main:not(.searching)" in css and "main.classList.toggle('searching'" in SETTINGS
    # and a card is kept when a row inside it matches, not only when its own words do
    assert "setSearchGroups(pm,v)" in SETTINGS and "function setSearchGroups" in SETTINGS


def test_agents_not_installed_are_rows_and_the_command_is_still_shown():
    i = SETTINGS.index("async function renderExecutors")
    body = SETTINGS[i:SETTINGS.index("function paintEngineSelect", i)]
    assert "pGroup('Not installed here'" in body
    assert "title=\"${esc(off.command)}\"" in body and "Install runs ${off.command}" in body


def test_the_agents_tab_splits_who_it_is_from_how_it_works():
    agent = _tab("agent")
    assert agent.index("pGroup('Lead agent'") < agent.index("pGroup('How it works'")
    how = agent[agent.index("pGroup('How it works'"):]
    for piece in ("s-workspace", "s-steps", "s-hist-compact", "s-build-model"):
        assert piece in how.split("],{f:")[0], piece
    assert "pGroup('Conversations'" not in agent
    share = (JS / "11c-agentshare.js").read_text()
    assert share.count('<div class="pgroup') >= 3          # share, host, fork
    assert 'type="checkbox" id="ags-soul"' not in share   # a switch now


def test_the_team_tab_is_in_groups():
    team = _tab("team")
    order = [g for g in _groups(team) if g]
    want = ["Models", "Asking each other", "Free talk", "Linked teams", "Messages"]
    assert [g for g in order if g in want] == want, order
    asking = team[team.index("pGroup('Asking each other'"):team.index("pGroup('Free talk'")]
    for piece in ("s-team-talk", "s-team-matrix", "s-team-limits"):
        assert piece in asking, piece
    assert "Community" in team
    # the limits are small boxes, not full-width fields
    assert ".prow.stack .pc .tl-row input[type=number]{width:96px" in (CSS / "11-prefs.css").read_text()


def test_accounts_open_on_mail_and_the_registration_is_folded():
    acc = _tab("accounts")
    assert acc.index('id="acct-list"') < acc.index("pGroup('GitHub'")
    a = (JS / "11d-accounts.js").read_text()
    assert '<details class="chsteps acct-reg" id="acct-reg">' in a and "function acctShowClients" in a
    # a Microsoft client id is not a Google one
    assert "s.id==='google'?'….googleusercontent.com'" in a


def test_channels_open_on_the_ones_you_set_up():
    i = SETTINGS.index("async function renderChannels")
    body = SETTINGS[i:SETTINGS.index("async function chanSave")]
    assert body.index("own.map(chanCard)") < body.index("built.map(chanCard)")
    assert "pRow('Available'" not in body
    assert "c.status==='needs'&&c.enabled?'open':''" in body


def test_speech_to_text_is_under_voice():
    voice = _tab("voice")
    assert "pGroup('Listening'" in voice and 'id="s-hear"' in voice and "v-lang" in voice
    kiosk = (JS / "24h-kiosk.js").read_text()
    face = kiosk[kiosk.index("async function faceSettingsPaint"):kiosk.index("async function hearSettingsPaint")]
    assert "s-face-hear" not in face and "settingsGo('voice')" in face
    assert "async function hearSettingsPaint" in kiosk
    places = (JS / "05b-places.js").read_text()
    assert "'Settings → Voice → Listening'" in places


def test_appearance_and_system_are_in_reading_order():
    look = _tab("look")
    assert "pGroup('Immersive experience'" not in look
    first = look[look.index("pGroup('Look'"):look.index("pGroup('Characters'")]
    assert "s-imm" in first and "s-imm-scene" in first and "s-theme" in first
    system = _tab("system")
    assert system.index("pGroup('Version'") < system.index("pGroup('People'")
    assert "settingsGo(\\'permissions\\')" not in system     # it is a tab of its own


def test_every_tab_has_a_tile_colour_in_the_immersive_look():
    imm = (CSS / "20-immersive.css").read_text()
    ids = re.findall(r"^\s+\['(\w+)','[^']*','[^']*','\w+'\],", SETTINGS, re.M)
    for i in ids:
        assert f"[data-t={i}] .psi{{background" in imm, f"the {i} tile has no colour"
    assert "body.immersive .pgroup.chan > h3{font-size:var(--fs-base)" in imm


def test_no_select_option_in_settings_is_long_enough_to_be_cut():
    # measured: a select cuts its label past about 34 characters at 340px
    for tab in ("agent", "permissions", "system", "look"):
        for label in re.findall(r"\['[\w.-]+','([^']+)'\]", _tab(tab)):
            assert len(label) <= 40, f"{tab}: {label!r}"
