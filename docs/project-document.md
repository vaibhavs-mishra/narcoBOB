# NarcoBob — Project Document

*IBM × NFSU Hackathon · Problem #11 · Track: AI*

## 1. The idea in one paragraph

Police seizure counts tell you where police are active; hospital overdose admissions tell
you where drugs are hurting people. When overdoses climb in an area while seizures stay
flat, a new supply route is probably operating unnoticed. **NarcoBob** watches both signals
in real time on a hexagonal map of a district, flags areas where harm is *escalating*, and
has four **IBM Bob** AI agents review every flag before an officer sees it. One of them,
the **Skeptic**, exists only to find reasons the flag is wrong. What reaches the officer
is a short brief with evidence, the Skeptic's verdict, and recommended enforcement *and*
treatment actions.

## 2. How it works (simple version)

1. **Events come in**: overdose admissions, seizures, arrests, each with a place and a
   time. (In this prototype the feed is **simulated** and labelled so everywhere.)
2. **The map is cut into hexagons** of about 5 km² (Uber's open H3 grid), so it works for
   any area without district boundary files.
3. **Every 2 seconds a calculator scores each hexagon** from 0 to 100 using four
   measurements: are overdoses accelerating? are they outpacing enforcement? are the
   neighbours rising too? is this a statistically significant cluster (Getis-Ord Gi\*)?
   Each is compared with that hexagon's own normal level, so tiny numbers don't cause
   panic. This part is plain statistics: no AI, fully repeatable.
4. **When a hexagon crosses the HIGH line**, an alert is raised and the four agents run
   one after another:
   - **Data Steward**: is the data trustworthy (did a hospital stop reporting)?
   - **Spatial Analyst**: why is this area flagged, and which areas belong together?
   - **Skeptic**: tries to break the alert with five checks (enough events? robust to
     other weightings? a reporting gap? just a one-day police raid? one source only?) and
     confirms, downgrades or rejects it.
   - **Intel Writer**: writes the brief for the officer.
5. **The officer sees it live** on a command-centre screen: rising hexagons, the alert,
   the agents working, the verdict and the brief.

If IBM Bob is unavailable, identical rule-based agents take over, so the system always
works.

## 3. Architecture overview

```
 Events ──► Ingest ──► SQLite ──► Scoring engine (every 2 s) ──► Alerts
 (simulated                                                        │
  or real)                                                         ▼
                                                     Orchestrator runs 4 IBM Bob agents
                                                     (headless custom modes)
                                                                   │  tool calls only
                                                                   ▼
                                                     MCP tool harness (allowlists,
                                                     budgets, tracing) ◄──► SQLite
                                                                   │
 Command-centre UI ◄──────────── WebSocket (scores, alerts, agent activity, briefs)
```

- **Two speeds.** The scoring engine is fast and deterministic. The AI agents are slow,
  so they only run when an alert fires.
- **Agents have no direct access to anything.** They can only call ten specific tools,
  each checked (is this agent allowed? is its step active? is it within budget?) and
  logged. Every number in a brief comes from a logged tool call.
- **Evidence is frozen at the alert.** The live map keeps moving while agents think, so
  the tools recompute each area's evidence as it was when the alert fired.

Full details: [architecture.md](architecture.md).

## 4. Results on the simulated scenario

| What we planted | What NarcoBob did |
|---|---|
| New supply route (overdoses ×4 over 5 days, seizures flat) | HIGH in 4 simulated days, CRITICAL in 5; Skeptic confirmed; detected on 12 of 12 random seeds |
| One village jumping from ~0 to 5 overdoses | Flagged, then downgraded by the Skeptic (too little evidence) |
| A hospital going silent for 3 days | Downgraded (feed gap) |
| A one-day police raid (seizures ×8) | No alert; a seizure-count ranking falls for it |
| Nothing at all (calm map) | ~6.5 alerts per simulated month, ~3.8 after the Skeptic |

## 5. Key tools and technologies, and where they came from

| Tool / technology | Used for | Source |
|---|---|---|
| **IBM Bob Shell 2.0** | Runtime of the four agents (headless custom modes, MCP client) | IBM, https://bob.ibm.com (installed from IBM's official installer) |
| Model Context Protocol Python SDK (FastMCP) | The agents' tool harness server | Anthropic / MCP project, https://github.com/modelcontextprotocol/python-sdk (PyPI `mcp`) |
| Python 3.12, FastAPI, Uvicorn, Pydantic, NumPy, pandas | Backend, engine, validation | python.org; PyPI (open source) |
| H3 (`h3` v4, `h3-js`) | Hexagonal spatial index | Uber, https://h3geo.org (open source) |
| SQLite | Storage | https://sqlite.org (bundled with Python) |
| Jinja2, PyYAML, python-ulid, httpx, honcho | Report templates, scenarios, IDs, HTTP, process runner | PyPI (open source) |
| React, Vite, TypeScript | Frontend | npm (open source) |
| Blueprint.js | UI components | Palantir, https://blueprintjs.com (open source) |
| deck.gl, MapLibre GL, react-map-gl | 3D map rendering | vis.gl / MapLibre, npm (open source) |
| CARTO dark-matter basemap | Map tiles | CARTO, © OpenStreetMap contributors |
| Zustand, Recharts, react-markdown, remark-gfm | UI state, charts, brief rendering | npm (open source) |
| dockview | Dockable, resizable, pop-out panel layout | npm (open source) |
| uv, ruff, mypy, pytest, oxlint | Packaging, linting, typing, tests | Astral, PyPI, npm (open source) |
| Statistical methods: Getis-Ord Gi\*, robust z-scores (median/MAD), OLS trends, Dirichlet weight sensitivity | Scoring engine | Standard spatial-statistics literature; implemented from scratch in `src/narcobob/engine/` |
| Public figures cited in the docs | Problem framing | NDDTC–AIIMS *Magnitude of Substance Use in India* (PIB, 2019); NCRB *Crime in India 2021* (via The Tribune, 2022) |

The event data is **synthetic**, generated by our own simulator (`src/narcobob/simulator/`).
No personal or real case data is used.

## 6. Limitations (honest)

Simulated data only; thresholds tuned on the synthetic scenario; a full Bob review takes
3–5 minutes; single machine, no login; the system predicts *places*, never people, by
design.

## 7. How to run

```bash
cd src && make setup && make dev-fallback   # or `make dev` with IBM Bob; open http://localhost:5173
```

Step by step: [setup-guide.md](setup-guide.md).
