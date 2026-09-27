"""`make backtest`: offline detection metrics for a scenario, plus the calm false-alarm test."""

from __future__ import annotations

import argparse
import json
import logging
from datetime import UTC, datetime
from typing import Any

from narcobob.backtest.metrics import false_alarm_metrics, scenario_metrics
from narcobob.backtest.simulate import build_world, cooldown_days, replay
from narcobob.common.config import SRC_DIR, get_settings
from narcobob.common.logging import setup_logging
from narcobob.simulator.scenario import load_scenario

log = logging.getLogger(__name__)


def run_backtest(scenario_name: str, seed: int, days: int, calm: str | None) -> dict[str, Any]:
    settings = get_settings()
    scenario = load_scenario(SRC_DIR / "scenarios" / f"{scenario_name}.yaml")
    scenario.auto_injections = True
    cooldown = cooldown_days(settings)
    rep = replay(build_world(scenario, seed, days), settings.weights, settings.thresholds, cooldown)
    result: dict[str, Any] = {
        "scenario": scenario_name,
        "seed": seed,
        "sim_days": days,
        "weights": list(settings.weights),
        "thresholds": list(settings.thresholds),
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "data": "SIMULATED",
        **scenario_metrics(rep),
    }
    if calm:
        calm_scenario = load_scenario(SRC_DIR / "scenarios" / f"{calm}.yaml")
        calm_rep = replay(
            build_world(calm_scenario, seed, days), settings.weights, settings.thresholds
        )
        result["calm"] = {"scenario": calm, **false_alarm_metrics(calm_rep)}
    return result


def print_table(r: dict[str, Any]) -> None:
    lines = [f"\nNarcoBob backtest: {r['scenario']} (seed {r['seed']}, {r['sim_days']} sim-days)"]
    lines.append("  data: SIMULATED")
    if "detection" in r:
        d, b = r["detection"], r["baselines"]
        lines += [
            f"  S1 true hotspot: HIGH after {d['days_to_high']} d,"
            f" CRITICAL after {d['days_to_critical']} d, verdicts {d['s1_final_verdicts']}",
            f"  precision@5 after onset: {d['precision_at_5']}",
            "  naive baselines, days until an S1 cell is top-5:"
            f" raw overdoses {b['raw_overdose_rank_days_to_top5']},"
            f" raw seizures {b['raw_seizure_rank_days_to_top5']}",
            "  naive baselines, precision@5 after onset:"
            f" raw overdoses {b['raw_overdose_rank_precision_at_5']},"
            f" raw seizures {b['raw_seizure_rank_precision_at_5']}",
        ]
    for decoy_id, v in r.get("decoys", {}).items():
        lines.append(
            f"  {decoy_id} ({v['kind']}): {v['alerts_pre_skeptic']} alerts →"
            f" {v['alerts_post_skeptic']} after Skeptic {v['verdicts']};"
            f" raw-seizure baseline flags it: {v['raw_seizure_rank_flags_it']}"
        )
    if "calm" in r:
        c = r["calm"]
        lines.append(
            f"  calm: {c['alerts_per_month_pre_skeptic']} → {c['alerts_per_month_post_skeptic']}"
            f" HIGH+ alerts/month after Skeptic; CRITICAL alerts: {c['critical_alerts']}"
        )
        lines.append(
            "  calm, naive rankings (new top-5 entries/month): raw overdoses"
            f" {c['raw_overdose_top5_entries_per_month']},"
            f" raw seizures {c['raw_seizure_top5_entries_per_month']}"
        )
    print("\n".join(lines))


def main() -> None:
    setup_logging()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", default="demo_border_surge")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--calm", default="calm", help="false-alarm scenario ('' to skip)")
    args = parser.parse_args()
    result = run_backtest(args.scenario, args.seed, args.days, args.calm or None)
    out = SRC_DIR / "recordings" / f"backtest_{args.scenario}.json"
    out.write_text(json.dumps(result, indent=2))
    print_table(result)
    print(f"\n  written to {out.relative_to(SRC_DIR)}")
