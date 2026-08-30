"""Catalog completeness: a missing or fuzzy translation fails the build."""
from pathlib import Path

import pytest
from babel.messages.pofile import read_po

TR = Path(__file__).parent.parent / "cti" / "translations"
LOCALES = ["zh_CN", "zh_TW"]


def _catalog(path, locale=None):
    with open(path, "rb") as f:
        return read_po(f, locale=locale)


def _ids(catalog):
    return {m.id for m in catalog if m.id}


@pytest.mark.parametrize("locale", LOCALES)
def test_catalog_complete_and_not_fuzzy(locale):
    cat = _catalog(TR / locale / "LC_MESSAGES" / "messages.po", locale)
    empty = [m.id for m in cat if m.id and not m.string]
    fuzzy = [m.id for m in cat if m.id and m.fuzzy]
    assert not empty, f"{locale}: untranslated {empty}"
    assert not fuzzy, f"{locale}: fuzzy {fuzzy}"


@pytest.mark.parametrize("locale", LOCALES)
def test_catalog_matches_pot(locale):
    pot = _ids(_catalog(TR / "messages.pot"))
    po = _ids(_catalog(TR / locale / "LC_MESSAGES" / "messages.po", locale))
    assert po == pot, f"{locale}: missing {pot - po}, stale {po - pot}"


@pytest.mark.parametrize("locale", LOCALES)
def test_mo_compiled_and_fresh(locale):
    po = TR / locale / "LC_MESSAGES" / "messages.po"
    mo = TR / locale / "LC_MESSAGES" / "messages.mo"
    assert mo.exists(), f"run: cti i18n compile"
    assert mo.stat().st_mtime >= po.stat().st_mtime, f"{locale}: .mo older than .po — run: cti i18n compile"


@pytest.mark.parametrize("locale", LOCALES)
def test_placeholders_preserved(locale):
    cat = _catalog(TR / locale / "LC_MESSAGES" / "messages.po", locale)
    import re
    for m in cat:
        if not m.id:
            continue
        assert set(re.findall(r"%\(\w+\)s", m.id)) == set(re.findall(r"%\(\w+\)s", m.string)), m.id
