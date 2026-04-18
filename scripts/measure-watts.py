#!/usr/bin/env python3
"""
measure-watts — ground-truth the sustainability claim.

Samples /sys/class/power_supply/BAT*/power_now at 1Hz for a labeled
interval. Stores the result in ~/.scatter/watts-baseline.jsonl. Over
time, this builds an evidence table:

  scenario=idle              mean=3.2W  n=60
  scenario=scatter-idle      mean=5.8W  n=60   (Scatter GUI open, idle)
  scenario=scatter-building  mean=22.1W n=90   (Ollama 7B inference)
  scenario=scatter-router    mean=14.0W n=30   (Ollama 3B routing)

Those numbers replace the estimates currently used in scatter_core.
watts_log when we later calibrate. Until then, they sit in the thesis
as "the actual power cost of the work."

Caveat: BAT0/power_now only reports accurate instantaneous draw when
the laptop is ON BATTERY. On AC power it may read 0 or show charging
current. The tool detects this and warns.

Usage:
  python3 measure-watts.py record <scenario> [--seconds N]   default 30
  python3 measure-watts.py summary                           show all recorded
  python3 measure-watts.py compare idle scatter-building     diff two scenarios
"""

from __future__ import annotations

import argparse
import datetime
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import scatter_core as sc  # noqa: E402


POWER_SUPPLY_DIR = Path("/sys/class/power_supply")
BASELINE_LOG = Path.home() / ".scatter" / "watts-baseline.jsonl"


def _find_battery() -> Path:
    for p in sorted(POWER_SUPPLY_DIR.glob("BAT*")):
        if (p / "power_now").is_file():
            return p
    raise RuntimeError("no battery found with power_now sensor (laptop required)")


def _ac_online() -> bool:
    for p in POWER_SUPPLY_DIR.glob("A*"):
        online = p / "online"
        if online.is_file():
            try:
                if online.read_text().strip() == "1":
                    return True
            except OSError:
                pass
    return False


def _sample_uW(bat: Path) -> int:
    """Return power_now in microwatts."""
    return int((bat / "power_now").read_text().strip())


def _status(bat: Path) -> str:
    try:
        return (bat / "status").read_text().strip()
    except OSError:
        return "unknown"


def record(scenario: str, seconds: int) -> int:
    bat = _find_battery()
    status = _status(bat)

    on_ac = _ac_online()
    if on_ac and status == "Charging":
        print(f"  ⚠ laptop is on AC and charging. BAT0/power_now reads charge rate, not system load.")
        print(f"    Unplug for true system watts measurement, or accept this is a calibration-limited run.")

    print(f"  recording scenario='{scenario}' for {seconds}s (1 Hz)")
    print(f"  battery status: {status}")

    samples_uW: list[int] = []
    started = datetime.datetime.now(datetime.timezone.utc).isoformat()
    t0 = time.monotonic()

    try:
        while time.monotonic() - t0 < seconds:
            try:
                samples_uW.append(_sample_uW(bat))
            except (OSError, ValueError):
                pass
            # Print live every 5 seconds
            elapsed = int(time.monotonic() - t0)
            if elapsed > 0 and elapsed % 5 == 0 and len(samples_uW) > 0:
                last = samples_uW[-1] / 1_000_000
                print(f"    [{elapsed:3d}s] last sample: {last:.2f} W", end="\r")
            time.sleep(1.0)
    except KeyboardInterrupt:
        print()
        print("  interrupted — saving what we have")

    if not samples_uW:
        print("  ✗ no samples collected", file=sys.stderr)
        return 1

    watts = [s / 1_000_000 for s in samples_uW]
    entry = {
        "scenario": scenario,
        "started": started,
        "seconds_requested": seconds,
        "n_samples": len(watts),
        "battery_status_at_start": status,
        "on_ac": on_ac,
        "watts": {
            "min": round(min(watts), 3),
            "max": round(max(watts), 3),
            "mean": round(statistics.mean(watts), 3),
            "median": round(statistics.median(watts), 3),
            "stdev": round(statistics.stdev(watts), 3) if len(watts) > 1 else 0.0,
        },
    }

    BASELINE_LOG.parent.mkdir(parents=True, exist_ok=True)
    with BASELINE_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    sc.journal_append("watts_baseline_recorded", scenario=scenario, **entry["watts"])

    print()
    print(f"  ✓ scenario '{scenario}' recorded (n={len(watts)})")
    print(f"    min={entry['watts']['min']:.2f}  "
          f"mean={entry['watts']['mean']:.2f}  "
          f"max={entry['watts']['max']:.2f}  "
          f"stdev={entry['watts']['stdev']:.2f}  W")
    return 0


def _read_all_entries() -> list[dict]:
    if not BASELINE_LOG.is_file():
        return []
    out = []
    for line in BASELINE_LOG.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def summary() -> int:
    entries = _read_all_entries()
    if not entries:
        print("  no watts baseline recordings yet.")
        print("  try: measure-watts record idle --seconds 30")
        return 0

    # Group by scenario, take most recent per scenario
    by_scenario: dict[str, dict] = {}
    for e in entries:
        key = e.get("scenario", "?")
        if key not in by_scenario or e.get("started", "") > by_scenario[key].get("started", ""):
            by_scenario[key] = e

    print()
    print(f"  {'SCENARIO':<30} {'MEAN (W)':>10} {'MIN':>7} {'MAX':>7} {'STDEV':>7} {'N':>5}")
    print(f"  {'-'*30} {'-'*10} {'-'*7} {'-'*7} {'-'*7} {'-'*5}")
    for scenario in sorted(by_scenario):
        e = by_scenario[scenario]
        w = e["watts"]
        print(f"  {scenario:<30} {w['mean']:>10.2f} {w['min']:>7.2f} {w['max']:>7.2f} "
              f"{w['stdev']:>7.2f} {e['n_samples']:>5}")
    print()
    print(f"  {len(entries)} total recordings across {len(by_scenario)} scenarios in {BASELINE_LOG}")
    return 0


def compare(a: str, b: str) -> int:
    entries = _read_all_entries()
    by_scenario: dict[str, dict] = {}
    for e in entries:
        key = e.get("scenario", "?")
        if key not in by_scenario or e.get("started", "") > by_scenario[key].get("started", ""):
            by_scenario[key] = e

    if a not in by_scenario or b not in by_scenario:
        missing = [x for x in (a, b) if x not in by_scenario]
        print(f"  scenario(s) not recorded yet: {', '.join(missing)}", file=sys.stderr)
        return 2

    ea, eb = by_scenario[a], by_scenario[b]
    wa, wb = ea["watts"], eb["watts"]
    delta = wb["mean"] - wa["mean"]
    ratio = wb["mean"] / wa["mean"] if wa["mean"] > 0 else float("inf")

    print()
    print(f"  {a}: mean={wa['mean']:.2f} W (n={ea['n_samples']})")
    print(f"  {b}: mean={wb['mean']:.2f} W (n={eb['n_samples']})")
    print()
    print(f"  delta: {delta:+.2f} W  ({ratio:.2f}× {a})")
    print()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="measure-watts")
    sub = parser.add_subparsers(dest="verb", required=True)

    p_r = sub.add_parser("record", help="record watts for a labeled scenario")
    p_r.add_argument("scenario", help="label (e.g. idle, scatter-idle, scatter-building)")
    p_r.add_argument("--seconds", type=int, default=30)

    sub.add_parser("summary", help="show most-recent recording per scenario")

    p_c = sub.add_parser("compare", help="diff two scenarios")
    p_c.add_argument("a")
    p_c.add_argument("b")

    args = parser.parse_args()
    try:
        if args.verb == "record":
            return record(args.scenario, args.seconds)
        if args.verb == "summary":
            return summary()
        if args.verb == "compare":
            return compare(args.a, args.b)
    except RuntimeError as e:
        print(f"measure-watts: {e}", file=sys.stderr)
        return 2
    return 1


if __name__ == "__main__":
    sys.exit(main())
