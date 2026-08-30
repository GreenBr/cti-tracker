# cti-tracker

Personal tracker for PRC-related cyber attack intelligence (both directions: China-attributed actors attacking outward, and attacks on Chinese targets). Fetches public reports/news (zh + en), extracts actors / incidents / TTPs with `claude -p` on your Claude subscription (no API key), and serves a Datasette dashboard.

## Setup
```bash
uv venv .venv && uv pip install -p .venv/bin/python -e ".[dev]"   # or python3 -m venv if python3-venv is installed
.venv/bin/cti init            # schema + ATT&CK China actors + sources.yaml
```

## Daily use
```bash
.venv/bin/cti fetch                       # pull feeds, pre-filter
.venv/bin/cti extract --limit 20          # claude -p on candidates (run 1–2x/day)
.venv/bin/cti extract --retry-failed      # only when you want to re-run failures
.venv/bin/cti serve                       # http://127.0.0.1:8001
```

Views: `/cti/actors`, `/cti/incidents` (facets: direction / country / sector / actor), `/-/dashboards/trends`, `/cti/new_today`, `/cti/actor_profile?actor=APT41` (also `actor_ttps`, `actor_sectors`).

## Configure
- `sources.yaml` — feeds (`enabled: false` to pause one; disabled entries carry a `note:` with the reason)
- `keywords.yaml` — pre-filter words (actor aliases are added automatically)
- `prompts/extract.md` — extraction instructions
- `schema/extract.json` — output contract

## Tests
`.venv/bin/pytest` — no network, no real `claude`.

Design: `docs/superpowers/specs/2026-08-30-cti-tracker-design.md` · Plan: `docs/superpowers/plans/2026-08-30-cti-tracker-v1.md`
