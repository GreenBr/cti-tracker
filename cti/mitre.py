"""MITRE ATT&CK Enterprise STIX import: China-attributed intrusion sets."""
from __future__ import annotations

import json
import re
from pathlib import Path

import requests

ATTACK_URL = ("https://raw.githubusercontent.com/mitre-attack/attack-stix-data/master/"
              "enterprise-attack/enterprise-attack.json")
# Attribution phrases: the group is *from* China, not merely targeting China.
CHINA_ATTRIBUTION = re.compile(
    r"(china[- ]based|chinese[- ]based|china[- ]nexus|chinese[- ]nexus|china[- ]linked|"
    r"chinese[- ](state|speaking|government|affiliated|sponsored|origin)|"
    r"chinese (cyber ?espionage|espionage|threat|apt|hack\w*|group|actor|intelligence|military|ministry)|"
    r"people'?s republic of china|\bprc\b|china'?s (ministry|people|state|government|military)|"
    r"attributed to (the )?(chinese|china|prc)|suspected (chinese|china)|"
    r"links? to (the )?(chinese|china)|based in china|"
    r"operat\w* (from|out of|within|in) (the )?([\w' ]+ province of )?china|province of china|"
    r"ministry of state security|\bmss\b|\bpla\b|people'?s liberation army)",
    re.IGNORECASE,
)


def load_bundle(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def download_bundle(dest: Path) -> dict:
    resp = requests.get(ATTACK_URL, timeout=120)
    resp.raise_for_status()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(resp.content)
    return resp.json()


def _mitre_id(obj: dict) -> str | None:
    for ref in obj.get("external_references", []):
        if ref.get("source_name") == "mitre-attack":
            return ref.get("external_id")
    return None


def china_intrusion_sets(bundle: dict) -> list[dict]:
    out = []
    for obj in bundle.get("objects", []):
        if obj.get("type") != "intrusion-set":
            continue
        if obj.get("revoked") or obj.get("x_mitre_deprecated"):
            continue
        if not CHINA_ATTRIBUTION.search(obj.get("description") or ""):
            continue
        name = obj["name"]
        aliases = sorted({a for a in obj.get("aliases", []) if a != name})
        out.append({
            "name": name,
            "aliases": aliases,
            "mitre_id": _mitre_id(obj),
            "description": obj.get("description"),
            "attributed_country": "CN",
        })
    out.sort(key=lambda g: g["name"])
    return out
