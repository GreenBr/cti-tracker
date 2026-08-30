"""Locale configuration for the web UI. All mechanics come from starlette-babel / Babel."""
from __future__ import annotations

from pathlib import Path

from babel import Locale
from starlette_babel import (LocaleFromCookie, LocaleFromHeader, LocaleFromQuery, LocaleMiddleware, get_locale,
                             gettext_lazy, load_messages_from_directories)

# gettext-style identifiers: they match what browsers send (zh-CN / zh-TW) so header negotiation is exact.
SUPPORTED = ["en", "zh_CN", "zh_TW"]
DEFAULT = "en"
COOKIE = "lang"
COOKIE_MAX_AGE = 30 * 24 * 3600
TRANSLATIONS_DIR = Path(__file__).resolve().parent.parent / "translations"

# Stored enum values -> human labels (translated at render time in the active locale).
ENUM_LABELS = {
    "direction": {
        "from_cn": gettext_lazy("From China (PRC-attributed actor)"),
        "to_cn": gettext_lazy("Against China (target inside PRC)"),
        "unclear": gettext_lazy("Unclear"),
    },
    "confidence": {
        "high": gettext_lazy("High"),
        "medium": gettext_lazy("Medium"),
        "low": gettext_lazy("Low"),
    },
    "relevance": {
        "pending": gettext_lazy("Pending"),
        "candidate": gettext_lazy("Candidate"),
        "skip": gettext_lazy("Skipped"),
    },
    "extract_status": {
        "pending": gettext_lazy("Pending"),
        "done": gettext_lazy("Done"),
        "failed": gettext_lazy("Failed"),
    },
    "source_type": {
        "vendor_report": gettext_lazy("Vendor report"),
        "news": gettext_lazy("News"),
        "gov_advisory": gettext_lazy("Government advisory"),
    },
}


def enum_label(kind: str, value: str | None) -> str:
    if value is None:
        return ""
    label = ENUM_LABELS.get(kind, {}).get(value)
    return str(label) if label is not None else str(value)


def locale_choices() -> list[tuple[str, str]]:
    """(code, native display name) pairs for the language switcher, names from CLDR via Babel."""
    out = []
    for code in SUPPORTED:
        loc = Locale.parse(code)
        native = Locale(loc.language, script=loc.script) if loc.script else loc
        out.append((code, native.get_display_name(native)))
    return out


def current_locale_code() -> str:
    """Map the active Babel Locale back to one of SUPPORTED (Babel expands zh_TW to zh_Hant_TW)."""
    active = get_locale()
    for code in SUPPORTED:
        if Locale.parse(code) == active:
            return code
    return DEFAULT


def load_catalogs() -> None:
    TRANSLATIONS_DIR.mkdir(parents=True, exist_ok=True)
    load_messages_from_directories([TRANSLATIONS_DIR])


def add_locale_middleware(app) -> None:
    app.add_middleware(
        LocaleMiddleware,
        locales=SUPPORTED,
        default_locale=DEFAULT,
        selectors=[LocaleFromQuery(query_param="lang"), LocaleFromCookie(cookie_name=COOKIE),
                   LocaleFromHeader(supported_locales=SUPPORTED)],
    )
