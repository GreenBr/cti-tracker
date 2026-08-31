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
.venv/bin/cti serve                       # web UI: http://127.0.0.1:8001
.venv/bin/cti datasette                   # raw tables / SQL (Datasette): http://127.0.0.1:8002
```

## Web UI
Pages: `/` (today), `/incidents` (filters: direction / country / sector / actor + full-text search), `/incidents/{id}`, `/actors`, `/actors/{id}`, `/articles/{id}`, `/trends` (charts with table view).

**Languages:** English (default), 简体中文 (`zh_CN`), 繁體中文 (`zh_TW`). Switch with the header selector (`?lang=zh_TW`, remembered in a cookie) or via the browser `Accept-Language` header. Only the UI is translated; extracted incident titles/summaries stay in English.

### i18n workflow (Babel + OpenCC, no hand-rolled parts)
```bash
.venv/bin/cti i18n extract      # source strings -> cti/translations/messages.pot
.venv/bin/cti i18n update       # merge new strings into zh_CN / zh_TW .po
# translate zh_CN/LC_MESSAGES/messages.po (Poedit or any editor)
.venv/bin/cti i18n gen-hant     # zh_CN -> zh_TW draft via OpenCC (s2twp); review it
.venv/bin/cti i18n compile      # .po -> .mo (committed so a fresh clone works)
.venv/bin/pytest tests/test_i18n.py   # fails on any missing/fuzzy string or stale .mo
```
Stack: FastAPI + Jinja2 (`jinja2.ext.i18n`), starlette-babel (locale negotiation, `gettext_lazy`, date filters), Babel (`pybabel`, `pofile`), OpenCC.

## Configure
- `sources.yaml` — feeds (`enabled: false` to pause one; disabled entries carry a `note:` with the reason)
- `keywords.yaml` — pre-filter words (actor aliases are added automatically)
- `prompts/extract.md` — extraction instructions
- `schema/extract.json` — output contract

## Publishing (Vercel, static)
```bash
.venv/bin/cti export        # renders the public site (all locales, no article bodies) into site/
git add site && git commit -m "data: refresh" && git push   # Vercel redeploys on push
```
The exported site is the **public mode**: incident summaries and metadata only — article full text never leaves your machine (copyright), with MITRE ATT&CK attribution in the footer. One-time setup: import the GitHub repo at vercel.com/new (framework: Other; output directory: `site`; no build command).

## Scheduled refresh (Windows Task Scheduler -> WSL)
`scripts/daily.sh` runs fetch -> extract -> export -> push and logs to `data/daily.log`. Registered as a daily
Windows scheduled task ("CTI Tracker Daily") so it runs even when WSL is idle, as long as the computer is on.
Register it via PowerShell — `schtasks /TR` mangles the wsl.exe arguments (the task then exits 0 without running anything):
```powershell
$a = New-ScheduledTaskAction -Execute 'C:\Windows\System32\wsl.exe' -Argument '-d Ubuntu -e /home/brandon/repos/cti-tracker/scripts/daily.sh'
$t = New-ScheduledTaskTrigger -Daily -At 09:00
$s = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 2)
Register-ScheduledTask -TaskName 'CTI Tracker Daily' -Action $a -Trigger $t -Settings $s
Unregister-ScheduledTask -TaskName 'CTI Tracker Daily' -Confirm:$false   # to remove
```
Missed runs (PC off/asleep at 09:00) fire as soon as the machine is next available (StartWhenAvailable).

## Tests
`.venv/bin/pytest` — no network, no real `claude`.

Design: `docs/superpowers/specs/2026-08-30-cti-tracker-design.md` · Plan: `docs/superpowers/plans/2026-08-30-cti-tracker-v1.md`
