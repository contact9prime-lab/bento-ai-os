"""The README in eleven languages, and the two ways that rots.

A translated README is not a file, it is a SET. It fails in two directions and
both are silent:

  * **One language falls out.** A switcher that lists eleven and ships ten is a
    dead link on the front page of the project, in a language the person reading
    it chose deliberately.
  * **The English one moves and the rest do not.** These are hand-written prose,
    not generated, so nothing makes them follow. A translation that has lost a
    whole section still looks fine — it just quietly documents a different
    program.

The second one cannot be fully checked without translating, so what is pinned
here is STRUCTURE: the same headings, in the same number. That catches a section
added to the English README and nowhere else, which is how this actually drifts.

One more thing, from how these arrived: they came off a branch whose commit
added `docs/screenshots/demo.gif` to the markup of all twelve files without ever
committing the asset. Every one of them rendered a broken image at the top. So
every link is resolved against the tree here, and that is the assertion that
would have caught it.
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
I18N = ROOT / "docs" / "i18n"
ENGLISH = ROOT / "README.md"

#: code -> the name it is offered under. The name matters: somebody scanning for
#: their language is looking for the word, not the ISO code.
LANGUAGES = {
    "zh-CN": "简体中文", "zh-TW": "繁體中文", "ja": "日本語", "ko": "한국어",
    "es": "Español", "pt-BR": "Português", "fr": "Français", "de": "Deutsch",
    "ru": "Русский", "hi": "हिन्दी", "ar": "العربية",
}


def _files() -> dict:
    return {p.name[len("README."):-len(".md")]: p
            for p in sorted(I18N.glob("README.*.md"))}


def _headings(text: str) -> list:
    return re.findall(r"^#{2,3}\s+.*$", text, re.M)


def _switcher(text: str) -> str:
    """The language bar — everything up to the end of the first <sub> block."""
    return text.split("</sub>", 1)[0]


# ------------------------------------------------------------------ the set

def test_every_offered_language_exists():
    have = _files()
    missing = [c for c in LANGUAGES if c not in have]
    assert not missing, f"offered but not shipped: {missing}"


def test_the_english_readme_offers_all_of_them():
    """The front page is where all but one of these is ever found."""
    en = ENGLISH.read_text()
    bar = _switcher(en)
    for code, name in LANGUAGES.items():
        assert f"docs/i18n/README.{code}.md" in bar, (
            f"the README's language bar does not offer {name} ({code})")


def test_each_translation_can_reach_every_other_one_and_english():
    """Otherwise a reader who lands on the Japanese one is stuck in Japanese —
    including when what they actually wanted was the English original."""
    for code, path in _files().items():
        bar = _switcher(path.read_text())
        assert '../../README.md' in bar, f"{code} cannot get back to English"
        for other in LANGUAGES:
            if other == code:
                continue
            assert f"README.{other}.md" in bar, f"{code} cannot reach {other}"


def test_each_translation_says_which_one_you_are_reading():
    """The current language is bold and not a link, in every one of these. Without
    it the bar is twelve identical links and no answer to "where am I"."""
    for code, path in _files().items():
        bar = _switcher(path.read_text())
        assert re.search(r"<b>[^<]+</b>", bar), (
            f"{code} does not mark the language you are currently reading")


# --------------------------------------------------------------- no dead links

def test_every_link_in_every_translation_resolves():
    """The bug this caught: a demo GIF referenced by all twelve files and
    committed by none of them."""
    dead = []
    for code, path in _files().items():
        for href in re.findall(r"\]\((\.\./[^)#]+)", path.read_text()):
            target = (I18N / href).resolve()
            if not target.exists():
                dead.append(f"{code} -> {href}")
    assert not dead, "dead links in the translated READMEs:\n  " + "\n  ".join(dead)


def test_the_english_readme_has_no_dead_local_links():
    en = ENGLISH.read_text()
    dead = [h for h in re.findall(r"\]\((docs/[^)#]+)", en) if not (ROOT / h).exists()]
    assert not dead, f"dead links in README.md: {dead}"


# ----------------------------------------------------------------- in step

def test_no_translation_has_lost_a_section():
    """Structure, because content cannot be checked here. A translation two
    sections short is documenting a program this one does not ship."""
    want = len(_headings(ENGLISH.read_text()))
    drifted = {code: len(_headings(p.read_text()))
               for code, p in _files().items()
               if len(_headings(p.read_text())) != want}
    assert not drifted, (
        f"the English README has {want} headings; these do not match: {drifted} "
        f"— a section was added or removed on one side only")


# --------------------------------------------- the same files, inside the product

def test_the_language_table_matches_what_is_on_disk():
    """`docs/` is force-included into the wheel and the Docs app globs it, so these
    files ship inside AgentOS as well as sitting on GitHub. The table the product
    reads them by has to be the same set, or the app lists a language the repo
    does not have — or, worse, ships one it cannot name."""
    from agentos import localeinfo

    assert set(localeinfo.DOC_LANGUAGES) == set(_files()), (
        "localeinfo.DOC_LANGUAGES and docs/i18n/ have drifted apart")


def test_a_machine_finds_its_own_language_and_does_not_guess():
    """Exact before bare, and never between two regional variants: `zh` is
    Simplified and Traditional, and picking one for somebody is worse than
    offering neither."""
    from agentos import localeinfo as L

    assert L.doc_language("ja-JP") == "ja"
    assert L.doc_language("hi_IN") == "hi"          # underscores are a real LANG
    assert L.doc_language("pt-BR") == "pt-BR"
    assert L.doc_language("pt") == "pt-BR"          # only one Portuguese to mean
    assert L.doc_language("zh") == ""               # two, so do not choose
    assert L.doc_language("en-GB") == ""            # English is the original
    assert L.doc_language("") == ""


def test_the_docs_app_titles_translations_by_language():
    """Otherwise the list gains eleven entries all called "Bento Box AI — …" in
    scripts most readers cannot tell apart, which is how shipping translations
    makes the docs harder to use rather than easier."""
    import asyncio

    from agentos import config as cfgmod
    from agentos import server as servermod

    servermod.state["cfg"] = cfgmod.load_config()
    docs = asyncio.run(servermod.api_docs())["docs"]
    translated = [d for d in docs if d.get("lang")]
    assert len(translated) == len(LANGUAGES), (
        "the Docs app does not list the translated overviews")
    for d in translated:
        assert d["title"].startswith("README — "), (
            f"{d['file']} is listed as {d['title']!r} rather than by its language")
        assert LANGUAGES[d["lang"]].split()[0] in d["title"]
