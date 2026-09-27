# NarcoBob: real-time narcotics hotspot intelligence, reviewed by IBM Bob agents

> Catch a new drug-supply route in the overdose data before the seizure statistics do,
> and let an adversarial AI Skeptic throw out the false alarms before they reach an officer.

**Feed disclaimer:** the event stream in this repository is **simulated** (calibrated in
spirit to public aggregates) and labelled as such everywhere. The pipeline is real.

---

## 👥 Team

| Field | Value |
|---|---|
| **Team Name** | _to be filled at submission_ |
| **Track** | AI |
| **Team Lead** | _to be filled at submission_ |
| **Members** | _to be filled at submission_ |

---

## 🎯 Problem Statement

District narcotics intelligence in Punjab is reactive and enforcement-biased: seizure and
arrest counts (which measure *police activity*) are read as "drug activity", hospital
overdose data sits in a separate silo, and a new supply route can harm people for weeks
before it shows up in monthly statistics. Punjab has India's highest NDPS case rate
(32.8 per lakh, NCRB 2021) and is among the states most affected by opioid use disorders
(NDDTC–AIIMS 2019). Details and sources: [docs/problem-statement.md](docs/problem-statement.md).

---

## 💡 Solution

A deterministic engine scores every H3 hexagon of a district every 2 seconds for
*escalating* harm, with harm-versus-enforcement divergence as a first-class signal. When an
area crosses a threshold, four **IBM Bob Shell** custom modes, *the Narclings*, review it
headless through a hardened MCP tool harness: a **Data Steward** checks the data, a
**Spatial Analyst** explains the signal, a **Skeptic** tries to break the alert, and an
**Intel Writer** publishes a brief with enforcement *and* treatment actions. It all streams
live into a dark command-centre UI. More: [docs/solution-overview.md](docs/solution-overview.md).

---

## ✨ Key Features

- **Harm-vs-enforcement divergence scoring:** acceleration, divergence, spillover and a
  Getis-Ord Gi\* hotspot statistic, each measured against the cell's own Poisson noise,
  combined into an explainable 0–100 score on an area-agnostic H3 grid.
- **IBM Bob as a headless multi-agent runtime:** four Bob Shell custom modes
  (`src/agents/.bob/`) run as a Steward → Analyst → Skeptic → Writer pipeline for every
  alert, acting only through a 10-tool MCP harness with per-agent allowlists,
  active-step authorisation, budgets and full tracing.
- **An adversarial Skeptic:** five checks (support, weight sensitivity, feed gaps,
  enforcement artefacts, single-source dependence) on evidence frozen as of the alert;
  its verdict is the final severity. It removes ~40% of engine alerts on a calm map and
  confirms the planted hotspot.
- **Real-time command centre:** live 3D hexagon map, alert feed (engine → Skeptic
  severity), cell evidence drawer, agent swim-lanes with live tool calls, and briefs.
- **Never a single point of failure:** deterministic fallback agents with identical
  schemas (`make dev-fallback`), and replay of a recorded real Bob session (`make replay`).

---

## 🛠️ Tech Stack

| Category | Technologies |
|---|---|
| **Languages** | Python 3.12, TypeScript |
| **Frameworks** | FastAPI, asyncio, Pydantic v2, NumPy, h3 v4, MCP Python SDK (FastMCP); React 19, Vite, Blueprint.js, deck.gl, MapLibre, Zustand, Recharts |
| **IBM Technologies** | **IBM Bob Shell** (four headless custom modes as the agent runtime, project `.bob/` config, MCP integration) |
| **Databases** | SQLite (WAL mode) |
| **Other** | uv, honcho, pytest, ruff, mypy, oxlint, CARTO dark-matter basemap (OpenStreetMap data) |

---

## 📁 Repository Structure

```
├── src/                      # All source code (see src/README.md)
│   ├── narcobob/             # Python package: engine, api, harness, orchestrator, simulator, backtest, replay
│   ├── agents/               # IBM Bob workspace: .bob/custom_modes.yaml, per-mode rules, mcp.json, AGENTS.md
│   ├── frontend/             # React + Blueprint + deck.gl command-centre UI
│   ├── scenarios/            # Simulator scenarios (demo_border_surge, calm)
│   ├── recordings/           # Recorded real session for replay + backtest results
│   └── tests/                # Engine, harness contract, API and golden end-to-end tests
├── docs/                     # problem-statement, solution-overview, architecture, setup-guide
├── demo/                     # Screenshots, demo video link
├── presentation/             # Slide deck
└── submission.yaml           # Structured submission metadata
```

---

## ⚡ How to Run

From [docs/setup-guide.md](docs/setup-guide.md) (prerequisites: git, [uv](https://docs.astral.sh/uv/), Node.js 22+):

```bash
# 1. Clone the repo
git clone https://github.com/vaibhavs-mishra/narcoBOB.git
cd narcoBOB/src

# 2. Install dependencies (Python 3.12 via uv + frontend via npm)
make setup

# 3. Configure environment (all values have working defaults)
cp .env.example .env
# optional: set BOB_API_KEY for live IBM Bob agents

# 4. Run the project
make dev-fallback     # no Bob needed (rule-based agents)
make dev              # with IBM Bob Shell agents
# open http://localhost:5173 and press INJECT SURGE

# Checks
make test && make backtest
```

---

## 🖥️ Demo

| Artifact | Link |
|---|---|
| 📹 Demo Video | [See demo/demo-video-link.txt](demo/demo-video-link.txt) |
| 🌐 Live Demo | [See demo/live-demo-url.txt](demo/live-demo-url.txt) (not deployed; runs locally) |
| 🖼️ Screenshots | [See demo/screenshots/](demo/screenshots/) |
| 📊 Presentation | [See presentation/](presentation/) |

---

## ⚠️ Known Limitations

- **Simulated data.** No public real-time feed of seizures and overdose admissions
  exists; the stream is synthetic. The ingest API accepts real JSON/CSV feeds unchanged,
  but the thresholds are tuned on the synthetic scenario only.
- **Bob latency.** A four-agent Bob review takes about 3–5 minutes, so reviews trail the
  live map (agents judge evidence frozen at the alert). Runs are prioritised by severity
  and capped at six cells; in a noisy period, borderline alerts wait.
- **Detection is escalation, not volume.** A long-established hotspot stops being
  "escalating" and fades from HIGH after the surge plateaus; a volume ranking is better at
  "where is it worst right now".
- **Calm false alarms.** The engine raises ~6.5 alerts per simulated month on a calm map
  (~3.8 survive the Skeptic); one CRITICAL false alarm in 90 simulated days.
- **Single machine, no authentication**; desktop layout only (≥ 1280 px wide).

---

## 🏅 What We're Most Proud Of

1. **The Skeptic.** An AI agent whose job is to *disagree*, running five concrete checks
   on evidence frozen as of the alert, and whose verdict is what the officer sees. Watch it
   downgrade noise and confirm the planted route in the Agents tab.
2. **Harm vs enforcement.** Reading the *gap* between overdoses and seizures instead of
   seizures alone: our backtest's one-day police raid fools a seizure ranking but raises no
   NarcoBob alert.
3. **Bob as a runtime.** `src/agents/.bob/custom_modes.yaml` plus a hardened MCP harness
   (`src/narcobob/harness/`) turn IBM Bob Shell into a least-privilege, auditable,
   headless multi-agent system, with a deterministic orchestrator and fallback so it never
   breaks the demo.
4. **Honest engineering.** Our own backtest showed the first engine raising ~850 false
   alerts a month; we fixed the statistics (noise-calibrated components) rather than hide
   it, and we report where a naive baseline does well.
