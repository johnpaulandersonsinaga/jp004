# jp004 — Local Runbook

Agent instructions for running jp004 locally. This document is written
for AI agents (Muse, Hermes, or any equivalent agent) that need to
start, verify, maintain, or update jp004 without additional guidance
from the user. Follow it literally. If a step cannot be completed,
report the step and the reason, then stop. Do not guess.

## What jp004 is

jp004 is a personal, global investment terminal. The app
(`jp004.html`) runs in the browser. A small Flask server (`server.py`)
serves the app and proxies live prices from TradingView. There is no
account, no cloud database, and no order execution.

Trade data lives only in the browser's `localStorage`. The server never
stores trades.

## Defaults

| Item | Value |
| --- | --- |
| App directory (VM) | `~/workspace/jp004` |
| App directory (phone) | `/sdcard/jp004` |
| App file | `jp004.html` |
| Server file | `server.py` |
| Runtime (VM) | `~/workspace/jp004-venv/bin/python` |
| Port | `28634` |
| Browser URL | `http://127.0.0.1:28634/` |
| Health endpoint | `http://127.0.0.1:28634/api/health` |
| Log (VM) | `~/workspace/jp004-server-run-vm.log` |

On another machine, replace the VM paths with the local checkout path.
Keep the port and the browser URL unchanged whenever possible (see
"Origin" below).

## Agent rules

These rules override convenience. They exist to protect the user's
data.

1. **Never expose the server publicly.** Bind `127.0.0.1` only.
   Never use `0.0.0.0`, a public tunnel, or a public domain unless the
   user explicitly orders it.
2. **Never change the origin.** Browser data is keyed by origin
   (`scheme://host:port`). If the URL changes, the journal appears
   empty. Keep `http://127.0.0.1:28634/` exactly.
3. **Never delete user data.** Never delete trade, export, or backup
   files without an explicit user order naming the file.
4. **Backup before every change.** Copy the file or folder first,
   confirm the copy (checksum or listing), then edit. Never copy and
   edit in the same parallel step.
5. **Never start a duplicate service.** Check for a running process
   before launching. One server, one forward.
6. **Launch detached.** Use `nohup setsid ... & disown` so the service
   survives the terminal session. Never attach a service to an
   interactive session.
7. **Never edit from a stale copy.** Edit from the copy the user
   actually uses. After editing, sync the VM and phone copies and
   verify matching checksums.
8. **No credentials in chat, files, or logs.** Never request, store,
   print, or use passwords, API keys, private keys, or login cookies.
   The price endpoints require no login and no key.
9. **Respect rate limits.** Price refresh is batched by the server.
   Do not poll the price endpoints in a loop and do not run parallel
   downloads against the same source.

## Quick start

### 1. Check whether the server is already running

```bash
curl -s -m 5 http://127.0.0.1:28634/api/health
```

- If it answers `{"status": "ok"}`, the server is running. Do not
  start another one. Skip to step 3.
- If it does not answer, continue to step 2.

### 2. Start the server

```bash
cd ~/workspace/jp004
nohup setsid ~/workspace/jp004-venv/bin/python server.py \
  > ~/workspace/jp004-server-run-vm.log 2>&1 < /dev/null & disown
sleep 5
curl -s -m 5 http://127.0.0.1:28634/api/health
```

If port 28634 is already in use, the server selects the next free
port and prints the actual URL in the log. In that case, do not
silently accept the new port: report it, because the browser origin
will differ and the journal will appear empty. Resolve the port
conflict first.

### 3. Verify the app

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:28634/
curl -s http://127.0.0.1:28634/ | grep -o "<title>[^<]*</title>" | head -1
```

Expected: HTTP `200` and `<title>jp004</title>`.

### 4. If the browser is on another device: SSH forward

When the server and the browser are on different devices, keep the
origin identical with an SSH local forward, run on the browser's
device:

```bash
ssh -i ~/.ssh/id_vps -p 2222 -N \
  -L 28634:localhost:28634 localbug@localhost
```

Run it detached (`nohup setsid ... & disown`) and verify from that
device:

```bash
curl -s -m 5 http://127.0.0.1:28634/api/health
```

Do not change the browser URL to reach the server directly. A
different URL is a different origin and a different (empty) journal.

## Periodic health check

Check every 30 minutes, in this order:

1. Server health (`/api/health` from the server host). If it fails,
   restart once with the command in step 2, wait 5 seconds, and check
   again.
2. Forward health (`/api/health` from the browser's device), only if
   the server-to-device link is up. If it fails, restart the forward
   once, wait 4 seconds, and check again.
3. Stay silent when the service is healthy or recovered after one
   restart. Notify the user only if a restart fails, naming the
   failed step.

Never restart the server if the user has said it must stay stopped.
Never auto-start it on device reboot unless the user has ordered
auto-start.

## Updating the app

1. Back up the full app directory with a dated name, outside the app
   directory (for example `~/workspace/jp004-backup-YYYYMMDD.tar.gz`).
2. Edit or replace files, then verify syntax and checksums.
3. Restart the server only if `server.py` or `ref_table.csv` changed.
   `ref_table.csv` is loaded once at startup, so a CSV change
   requires a restart. An HTML-only change takes effect on the next
   browser load.
4. Verify health and HTTP 200 after the restart.
5. Sync the updated files to the phone copy (`/sdcard/jp004`) and
   verify matching checksums. Do not overwrite the phone copy with
   an older version.
6. Tell the user to refresh the browser tab. A stale cached page is
   the most common cause of "the change is not showing".

## Stopping the server

Only on the user's explicit order:

```bash
pkill -f "jp004-venv/bin/python server.py"
curl -s -m 5 http://127.0.0.1:28634/api/health || echo "server stopped"
```

Confirm the health endpoint no longer answers before reporting the
server as stopped.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Health check fails | Server not running | Start once (step 2), check the log |
| Health ok, browser empty | Origin changed | Restore `http://127.0.0.1:28634/` via forward, do not use a new URL |
| Browser shows the old page | Browser cache | Close and reopen the tab, or hard refresh |
| Port conflict on start | Another process on 28634 | Identify it, stop the duplicate if it is jp004, otherwise report it |
| Price refresh fails | TradingView scanner unavailable | Retry once later; do not hammer the endpoint |
| `ref_table.csv` change not visible | Server not restarted | Restart the server (step 2) |

## Files

| File | Purpose |
| --- | --- |
| `jp004.html` | The app (HTML, CSS, JavaScript) |
| `server.py` | Flask server: static files + price proxy |
| `ref_table.csv` | 81 exchanges: MIC, country, TradingView prefix, currency |
| `requirements.txt` | Flask, requests |
| `README.md` | User-facing project documentation |
| `INSTRUCTIONS.md` | This file: agent runbook |
| `.gitignore` | Excludes personal data exports, logs, and backups |

Personal export files (dated trade JSON or CSV files) are not part of
the repository and must never be committed.
