# Solution Overview

## What We Built

**NarcoBob** is a real-time narcotics intelligence system for a district officer. Events
(overdose admissions, drug seizures, NDPS arrests) stream in and are placed on a hexagonal
grid. A deterministic engine scores every hexagon continuously for *escalating* harm.
When an area crosses a threshold, four **IBM Bob** agents, the *Narclings*, review it:
a **Data Steward** checks the data, a **Spatial Analyst** explains the signal, a **Skeptic**
tries to break the alert, and an **Intel Writer** produces a brief with enforcement *and*
treatment recommendations. Everything appears live in a dark command-centre UI.

The event feed in this repository is **simulated** (clearly labelled everywhere); the
pipeline is real and accepts real event feeds or CSV uploads unchanged.

## How It Works

1. **Ingest.** Events arrive at `POST /api/ingest` (or as CSV). Each is validated,
   deduplicated, checked against the monitored area and assigned to an H3 hexagon
   (≈ 5 km²) and a one-day time bucket.
2. **Score (fast path, every 2 s).** The engine rebuilds a `[cell × event type × day]`
   count array for the last 60 days and computes four components per cell:
   - **Acceleration:** are overdoses rising faster this week than last?
   - **Harm vs enforcement divergence:** are overdoses growing faster than seizures and
     arrests? This is the key idea: seizures measure *police activity*, overdoses measure
     *harm*. When harm outpaces enforcement, a supply route is going undetected.
   - **Spillover:** are the neighbouring cells accelerating too?
   - **Getis-Ord Gi\*:** is this a statistically significant spatial cluster?

   Each component is measured **against the cell's own Poisson noise**, so a village going
   from 0 to 2 events does not look like an epidemic. They are combined into a 0–100 score
   and a severity (WATCH / HIGH / CRITICAL; CRITICAL also requires a significant hotspot
   and enough events).
3. **Alert.** A cell that enters HIGH or CRITICAL raises an alert. Alerts within 15 s are
   batched into one **agent run**, the most severe run first.
4. **Review (slow path, IBM Bob).** The orchestrator runs four Bob Shell custom modes
   headless, one after another. Each agent can act **only** through a hardened MCP tool
   harness (per-agent tool allowlist, active-step authorisation, call budget, response
   cap, and every call traced). Agents see the evidence **as it was when the alert
   fired**, recomputed by the engine, so reviews are reproducible even while the live map
   moves on.
   - The **Steward** reports feed gaps and single-source dependence.
   - The **Analyst** explains the drivers and groups adjacent cells into clusters.
   - The **Skeptic** runs five checks on every claim: enough events? robust to other
     reasonable weightings (Dirichlet sensitivity)? a reporting source went silent? a
     seizure spike without overdose growth (a raid artefact)? one source dominating? It
     then **confirms, downgrades, rejects** or asks for more data. **Its verdict is the final
     severity.**
   - The **Writer** publishes a brief in a fixed structure, with at least one enforcement
     and one treatment/prevention action (the tool rejects anything else) and only
     tool-sourced numbers.
5. **Show.** Everything streams over a WebSocket to the UI: rising hexagons, the alert
   feed (engine severity → Skeptic's final severity), the agents' tool calls in real time,
   and the brief.

## What Makes It Different

- **Harm-vs-enforcement divergence as a first-class signal.** Most tools rank places by
  seizures, which bakes enforcement bias into "risk". NarcoBob reads the gap between the
  two, and ignores a one-day raid (see the backtest).
- **An adversarial Skeptic agent.** Automated flags are cheap; trustworthy flags are not.
  The Skeptic is rewarded for catching false alarms and must justify every verdict with
  numbers from its tools. On a calm map it removes about 40% of engine alerts.
- **Bob is the runtime, not a chatbot.** Four Bob Shell custom modes run headless as a
  multi-agent pipeline. The deterministic orchestrator activates each step, checks the
  agent actually submitted its output, retries once and otherwise falls back to a
  rule-based twin, so the system never depends on a single point of failure.
- **The engine does the math; agents do judgment and language.** No LLM ever computes a
  score, and every number in a brief comes from a logged tool call.
- **Area-agnostic.** Change one bounding box and it monitors any region on Earth; H3
  needs no boundary files.

## Key Design Decisions

| Decision | Why |
|---|---|
| H3 hexagons instead of districts | Works anywhere, equal-area cells, adjacency for free |
| Components in units of each cell's own noise | Our first calibration raised ~850 false alerts a month on a calm map; noise-calibration brought it to ~6.5 |
| Two speeds: engine every 2 s, agents only on alerts | Bob reviews take minutes and cannot run per event |
| Agents communicate through an SQLite "blackboard" via MCP tools, never stdout | Stdout is unreliable to parse; tools are validated, authorised and traced |
| Evidence frozen "as of the alert" | The world moves on while agents think; verdicts must not judge a moved target |
| Deterministic fallback agents with identical schemas | The demo and the system must run without Bob |
| Recommend treatment alongside enforcement (incl. NDPS Act s.64A diversion) | Addresses harm, not just supply; heads off the predictive-policing critique |
| Predict places, never people | No personal data; ethically defensible |

## Results (backtest, simulated scenario, `make backtest`)

| Scenario element | What happened |
|---|---|
| **S1**: new supply route, overdoses ×4 over 5 days, seizures flat | HIGH after 4 sim-days, CRITICAL after 5; Skeptic **CONFIRMED** (detected on 12/12 seeds and start days) |
| **D1**: a rural cell jumps from ~0 to 5 overdoses | Flagged by the engine, **DOWNGRADED** by the Skeptic (too few events) |
| **D2**: a hospital stops reporting for 3 days | Alert **DOWNGRADED** (feed gap) |
| **D3**: one-day police raid, seizures ×8, overdoses flat | **No alert.** A seizure ranking flags it |
| Calm map (no events planted) | 6.5 engine alerts/month → 3.8 after the Skeptic; raw-count rankings churn ~53 new "hotspots"/month |

Honest caveat: a raw *overdose* ranking also finds S1, because it becomes the largest
overdose cluster; its advantage disappears on the calm map, where it cannot tell
escalation from volume.

## User Experience

1. The officer opens the command centre: a 3D map of the district, live KPIs, a flowing
   event ticker and a persistent **SIMULATED FEED** badge.
2. A new route opens (the **INJECT SURGE** button in the demo). Within seconds hexagons near
   the border rise and redden; a HIGH/CRITICAL alert flashes into the feed.
3. The **Narclings** lanes light up: tool calls blip across four swim-lanes, each tagged
   *IBM Bob*, with each agent's conclusion as it lands.
4. The alert updates: engine CRITICAL → **Skeptic CONFIRMED**. Nearby noise alerts are
   downgraded, with the reason shown.
5. Clicking the cell opens the evidence: score gauge, component contributions,
   overdose-vs-enforcement trend, the Skeptic's five checks. **Open brief** shows the
   officer-ready report.
6. The **Observability** view shows exactly what the agents did: every step, every MCP tool
   call (with latency, and any call the harness rejected), every finding, and each step's
   raw Bob Shell console output.

Every panel can be resized, dragged to a new position, floated over the page or popped out
into its own window; the layout is remembered. The **?** button (or the `?` key) marks each
part of the screen with a short explanation.
