# Setup Guide

> Written for someone who has never seen this repository. Every command runs from `src/`.
> **No IBM Bob account? Use fallback mode (step 5b). The whole system, including agent
> reviews and briefs, runs end to end without Bob.**

## 1. Prerequisites

| Tool | Version | Check | Install |
|---|---|---|---|
| git | any recent | `git --version` | your OS package manager |
| Python | 3.12 (installed automatically by uv) | `uv python list` | via uv |
| uv | 0.5+ | `uv --version` | https://docs.astral.sh/uv/getting-started/installation/ |
| Node.js | 22+ (tested on 26) | `node -v` | https://nodejs.org |
| IBM Bob Shell | 2.0+ (*optional*, for live Bob agents) | `bob --version` | step 4 |

Tested on Linux (CachyOS/Arch, x86-64) with Chrome and Firefox. A 1440×900 or larger
screen is needed for the command-centre UI.

## 2. Get the code and install dependencies

```bash
git clone https://github.com/vaibhavs-mishra/narcoBOB.git
cd narcoBOB/src
make setup          # = uv sync (Python deps, incl. Python 3.12) + npm install (frontend)
```

## 3. Configure

```bash
cp .env.example .env
```

Every variable has a working default; you only need to edit `.env` to use IBM Bob
(`BOB_API_KEY`) or to change the area.

| Variable | Default | What it does |
|---|---|---|
| `NARCOBOB_AGENTS_MODE` | `bob` | `bob`: the four agents run as IBM Bob Shell custom modes. `fallback`: deterministic rule-based agents (no Bob needed). |
| `BOB_BIN` | `bob` | Path to the Bob Shell binary (or a wrapper script) |
| `BOB_API_KEY` | — | Inference-scoped API key from the Bob portal, used for headless runs |
| `BOB_AGENT_TIMEOUT_S` | `180` | Timeout per agent step attempt (one retry, then fallback) |
| `NARCOBOB_AREA_NAME` | `Amritsar–Tarn Taran border belt` | Display name |
| `NARCOBOB_AREA_BBOX` | `31.20,74.50,31.90,75.20` | lat_min,lon_min,lat_max,lon_max — change it to monitor anywhere |
| `NARCOBOB_H3_RES` | `7` | H3 hexagon resolution (≈ 5 km² cells) |
| `NARCOBOB_BUCKET_SIM_SECONDS` | `86400` | One time bucket = one simulated day |
| `NARCOBOB_SIM_SECONDS_PER_WALL_SECOND` | `28800` | Demo speed: one simulated day every 3 s |
| `NARCOBOB_BACKFILL_BUCKETS` | `60` | Simulated days of history generated at start |
| `NARCOBOB_SCENARIO` / `NARCOBOB_SEED` | `demo_border_surge` / `42` | Scenario file in `src/scenarios/` and RNG seed |
| `NARCOBOB_SIM_AUTOSTART` | `true` | Simulator backfills and streams as soon as it starts |
| `NARCOBOB_SCORE_INTERVAL_S` | `2` | Scoring cadence (wall seconds) |
| `NARCOBOB_WEIGHTS` | `0.35,0.25,0.20,0.20` | Weights of acceleration, divergence, spillover, Gi* |
| `NARCOBOB_THRESHOLDS` | `65,82,90` | WATCH, HIGH, CRITICAL score thresholds |
| `NARCOBOB_ALERT_COOLDOWN_S` / `NARCOBOB_ALERT_COALESCE_S` | `120` / `15` | Per-cell alert cooldown; window that batches alerts into one agent run |
| `NARCOBOB_API_PORT` / `NARCOBOB_MCP_PORT` / `NARCOBOB_SIM_PORT` | `8000` / `8765` / `8001` | Local ports |
| `NARCOBOB_DB_PATH` | `var/narcobob.db` | SQLite database (relative to `src/`) |
| `NARCOBOB_RECORD` | `true` | Record every WebSocket message to `recordings/` |
| `NARCOBOB_REPLAY_FILE` / `NARCOBOB_REPLAY_SPEED` | `recordings/demo_golden.jsonl.gz` / `1` | What `make replay` plays, and how fast |
| `VITE_API_URL` / `VITE_WS_URL` | `http://localhost:8000` / `ws://localhost:8000/ws` | Where the UI finds the API |

## 4. (Optional) Install IBM Bob Shell

Needed only for `NARCOBOB_AGENTS_MODE=bob`.

1. Create an IBMid at https://bob.ibm.com/trial and, in the Bob portal, create an API key
   with scope **Inference**. Put it in `src/.env` as `BOB_API_KEY=...`.
2. Install Bob Shell (Node ≥ 24 required):
   ```bash
   curl -fsSL https://bob.ibm.com/download/bobshell.sh | bash
   ```
   If your npm global prefix needs root, install to your home directory instead, which is
   what the script does minus the prefix:
   ```bash
   v=$(curl -s https://s3.us-south.cloud-object-storage.appdomain.cloud/bob-shell/bobshell2-version.txt)
   curl -sLo bob.tgz https://s3.us-south.cloud-object-storage.appdomain.cloud/bob-shell/bobshell-$v.tgz
   npm install -g --prefix ~/.local --allow-scripts=@officecli/officecli ./bob.tgz   # ~/.local/bin on PATH
   ```
3. Check: `make bob-smoke` runs one headless Bob agent through the tool harness and
   prints `PASS` (about 15–20 s).

The agents' Bob configuration is committed in `src/agents/`: `.bob/custom_modes.yaml`
(four custom modes, MCP tool group only), `.bob/rules-narcobob-*/` (per-agent rules),
`.bob/mcp.json` (the harness endpoint and tool allowlist) and `AGENTS.md` (shared rules).

## 5. Run

### 5a. With IBM Bob agents

```bash
make dev
```

### 5b. Without Bob (fallback agents)

```bash
make dev-fallback
```

Both start four processes (API :8000, MCP tool harness :8765, simulator :8001, web :5173).
Open **http://localhost:5173**. The simulator backfills 60 simulated days, then streams
live at one simulated day every 3 seconds.

### 5c. Replay a recorded real run (no Bob, no simulator)

```bash
make replay
```

Plays `recordings/demo_golden.jsonl.gz`, a recorded session with real Bob agents, through the
same UI. The top bar shows **REPLAY**.

## 6. Verify it works

1. The top bar shows `SIMULATED FEED`, live KPIs, a running sim clock, and green API/MCP
   lights (BOB is green in `make dev`, "off" in fallback mode).
2. Click **INJECT SURGE** → **Inject**. Within about 15–30 seconds, hexagons near the
   border west of Amritsar rise and turn orange/red and HIGH/CRITICAL alerts appear on the left.
3. The **Agents** tab shows the four Narclings working: Steward → Analyst → Skeptic → Writer
   (seconds in fallback mode; about 3–5 minutes with Bob). Alerts then show the Skeptic's
   verdict (CONFIRMED / DOWNGRADED / REJECTED).
4. Click an alert: the drawer shows the score breakdown, trends and the Skeptic's checks.
   **Open brief** shows the intelligence brief with enforcement *and* treatment actions.

Automated checks:

```bash
make test        # 90+ tests: engine math, every harness tool, API, golden end-to-end run
make lint        # ruff, mypy --strict (engine + harness), oxlint, tsc
make backtest    # offline detection metrics on the demo scenario + calm false-alarm test
```

Other tools: `uv run narcobob-harness list` lists the agent tools and who may call them;
`make bob-run` runs one complete four-agent Bob review of a demo alert and prints the brief.

## 7. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| BOB light red in `make dev` | `bob` not on PATH or `BOB_API_KEY` missing | Check `which bob` and `src/.env`; or use `make dev-fallback` |
| Agent steps end as `fallback` in Bob mode | Bob timed out, or did not submit its output | Check the step log (`/api/runs/<run_id>`); Bob logs are in `~/.bob/logs/`; the fallback result is still valid |
| Map is black, no streets | Basemap blocked (offline) | The hexagons still render; the basemap needs internet (CARTO) |
| UI shows "Waiting for the area configuration…" | API not running | Check the `api` line in the `make dev` output |
| `address already in use` | A previous run is still up | Stop it (Ctrl-C) or free ports 8000/8001/8765/5173 |
| `make replay` exits "recording not found" | No recording | `recordings/demo_golden.jsonl.gz` ships with the repo; re-record with `scripts/save_recording.py` |
| Want a fresh start | Old data | Top bar ⋯ → **Reset scenario**, or delete `src/var/` |
