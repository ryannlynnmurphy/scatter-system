#!/usr/bin/env python3
"""
Scatter Power Router — Adaptive model selection based on energy state.

Intelligence per watt as a real function, not a philosophy.

The router reads system state and decides which model to use.
When energy is abundant: use the best model (highest intelligence).
When energy is scarce: use the fastest model (highest efficiency).
When energy is critical: refuse non-essential inference.

This is the optimization the research demands.
"""

import json
import os
import time
from pathlib import Path

STATE_PATH = os.path.expanduser("~/.scatter/system-state.json")
IPW_LOG_PATH = os.path.expanduser("~/.scatter/ipw-log.jsonl")


def read_state():
    try:
        with open(STATE_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def get_power_tier():
    """
    Determine the current power tier based on battery state.

    Returns:
        'full'     — battery >50% or charging. Use best model.
        'moderate' — battery 20-50%, not charging. Use fast model.
        'critical' — battery <20%, not charging. Minimal inference only.
        'plugged'  — on AC power. Use best model always.
    """
    state = read_state()
    battery = state.get("battery_pct")
    status = state.get("battery_status", "Unknown")

    if status == "Charging" or status == "Full":
        return "plugged"
    if battery is None:
        return "full"  # Desktop or unknown — assume power is fine
    if battery > 50:
        return "full"
    if battery > 20:
        return "moderate"
    return "critical"


def select_model(query_complexity="normal"):
    """
    Select the optimal model based on power tier and query complexity.

    Args:
        query_complexity: 'simple', 'normal', or 'complex'

    Returns:
        dict with 'model', 'ctx_size', 'reason', and 'tier'
    """
    tier = get_power_tier()

    BEST_MODEL = os.environ.get("SCATTER_MODEL", "qwen2.5-coder:7b")
    FAST_MODEL = os.environ.get("SCATTER_FAST_MODEL", "llama3.2:3b")

    if tier == "critical":
        if query_complexity == "complex":
            return {
                "model": FAST_MODEL,
                "ctx_size": 2048,
                "reason": f"Battery critical — using {FAST_MODEL} with minimal context",
                "tier": tier,
                "should_defer": True,
            }
        return {
            "model": FAST_MODEL,
            "ctx_size": 2048,
            "reason": f"Battery critical — lightweight mode",
            "tier": tier,
            "should_defer": False,
        }

    if tier == "moderate":
        if query_complexity == "simple":
            return {
                "model": FAST_MODEL,
                "ctx_size": 4096,
                "reason": f"Conserving power — simple query routed to {FAST_MODEL}",
                "tier": tier,
                "should_defer": False,
            }
        return {
            "model": BEST_MODEL,
            "ctx_size": 8192,
            "reason": f"Moderate power — using {BEST_MODEL} with reduced context",
            "tier": tier,
            "should_defer": False,
        }

    # full or plugged — use the best
    ctx = 32768 if tier == "plugged" else 16384
    return {
        "model": BEST_MODEL,
        "ctx_size": ctx,
        "reason": f"Power {'abundant' if tier == 'plugged' else 'good'} — full capability",
        "tier": tier,
        "should_defer": False,
    }


def log_inference(model, tokens_generated, elapsed_seconds, query_type="general"):
    """
    Log an inference event for intelligence-per-watt tracking.

    The metric: tokens generated per watt-second consumed.
    We approximate power from the model size:
      - 3B model ≈ 8W inference
      - 7B model ≈ 15W inference
    This is approximate. Real measurement would use RAPL or battery discharge rate.
    """
    model_power = {
        "llama3.2:3b": 8,
        "qwen2.5-coder:7b": 15,
    }
    power_w = model_power.get(model, 12)  # default estimate

    watt_seconds = power_w * elapsed_seconds
    ipw = tokens_generated / watt_seconds if watt_seconds > 0 else 0

    entry = {
        "timestamp": time.time(),
        "model": model,
        "tokens": tokens_generated,
        "elapsed_s": round(elapsed_seconds, 2),
        "power_w": power_w,
        "watt_seconds": round(watt_seconds, 2),
        "tokens_per_watt_second": round(ipw, 3),
        "query_type": query_type,
        "power_tier": get_power_tier(),
    }

    os.makedirs(os.path.dirname(IPW_LOG_PATH), exist_ok=True)
    with open(IPW_LOG_PATH, "a") as f:
        f.write(json.dumps(entry) + "\n")

    return entry


def get_ipw_summary():
    """Get intelligence-per-watt summary statistics."""
    if not os.path.isfile(IPW_LOG_PATH):
        return None

    entries = []
    with open(IPW_LOG_PATH) as f:
        for line in f:
            try:
                entries.append(json.loads(line))
            except Exception:
                pass

    if not entries:
        return None

    total_tokens = sum(e.get("tokens", 0) for e in entries)
    total_watt_seconds = sum(e.get("watt_seconds", 0) for e in entries)
    total_queries = len(entries)

    # Last 24h
    cutoff = time.time() - 86400
    recent = [e for e in entries if e.get("timestamp", 0) > cutoff]
    recent_tokens = sum(e.get("tokens", 0) for e in recent)
    recent_ws = sum(e.get("watt_seconds", 0) for e in recent)

    return {
        "total_queries": total_queries,
        "total_tokens": total_tokens,
        "total_watt_seconds": round(total_watt_seconds, 1),
        "total_watt_hours": round(total_watt_seconds / 3600, 3),
        "avg_tokens_per_watt_second": round(total_tokens / total_watt_seconds, 3) if total_watt_seconds > 0 else 0,
        "last_24h_queries": len(recent),
        "last_24h_tokens": recent_tokens,
        "last_24h_watt_hours": round(recent_ws / 3600, 3),
    }


if __name__ == "__main__":
    import sys
    if "--summary" in sys.argv:
        summary = get_ipw_summary()
        if summary:
            print(f"\n  Intelligence Per Watt — Summary")
            print(f"  Total queries:     {summary['total_queries']}")
            print(f"  Total tokens:      {summary['total_tokens']}")
            print(f"  Total energy:      {summary['total_watt_hours']} Wh")
            print(f"  Avg efficiency:    {summary['avg_tokens_per_watt_second']} tok/Ws")
            print(f"  Last 24h queries:  {summary['last_24h_queries']}")
            print(f"  Last 24h energy:   {summary['last_24h_watt_hours']} Wh")
        else:
            print("  No inference data yet.")
    else:
        selection = select_model()
        print(f"\n  Power tier:  {selection['tier']}")
        print(f"  Model:       {selection['model']}")
        print(f"  Context:     {selection['ctx_size']}")
        print(f"  Reason:      {selection['reason']}")
