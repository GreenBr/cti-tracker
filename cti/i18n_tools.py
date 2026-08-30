"""Catalog helpers built on Babel's pofile API and OpenCC (no hand-rolled parsing)."""
from __future__ import annotations

from pathlib import Path

from babel.messages.pofile import read_po, write_po
from opencc import OpenCC


def generate_zh_tw(src_po: Path, dst_po: Path, config: str = "s2twp") -> int:
    """Convert every translated msgstr in the zh_CN catalog to Traditional (Taiwan phrasing).

    Untranslated entries stay empty; existing zh_TW entries are overwritten (the zh_CN catalog is the source of truth
    for the automatic pass; manual fixes belong in zh_TW after review and are preserved only if you re-run with care).
    """
    cc = OpenCC(config)
    with open(src_po, "rb") as f:
        catalog = read_po(f, locale="zh_CN")
    catalog.locale = "zh_TW"
    catalog.language_team = "zh_TW <LL@li.org>"
    n = 0
    for msg in catalog:
        if not msg.id:
            continue
        if isinstance(msg.string, (list, tuple)):
            msg.string = tuple(cc.convert(s) if s else s for s in msg.string)
        elif msg.string:
            msg.string = cc.convert(msg.string)
        n += 1
    dst_po.parent.mkdir(parents=True, exist_ok=True)
    with open(dst_po, "wb") as f:
        write_po(f, catalog, width=100)
    return n
