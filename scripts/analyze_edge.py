#!/usr/bin/env python3
"""
Market Maker Edge Quantification Framework

Analyzes a market maker's trading signal by matching each fill against
real-time market state to decompose their edge into:
1. Execution edge (fill price vs market mid — maker spread capture)
2. Selection edge (which windows they trade vs skip)
3. Timing edge (when within a window they accelerate/decelerate)
4. Aggression triggers (what causes the switch from passive to crossing)

The key insight: a market maker's BEHAVIOR reveals their model's beliefs,
even if we can't see the model itself. By analyzing 3M+ fills against
price data, we can extract:
- What imbalance level triggers aggressive fills
- What time in the window they get urgent
- Whether they skip certain window types (selection bias = a signal)
- How their fill patterns differ in winning vs losing windows

Data requirements:
    - Wallet fill history (JSON from Subgraph API)
    - Price log (CSV: timestamp, yes_price, no_price per market)

Note: Uses only publicly available on-chain data.
"""

import json
import csv
import os
import numpy as np
from collections import defaultdict
from datetime import datetime, timezone
from statistics import mean, median, stdev
from bisect import bisect_left
from typing import Optional


# ── Data Loading ──────────────────────────────────────────────────────

def load_fills(filepath: str) -> dict:
    """Load fill history grouped by window slug, sorted by timestamp."""
    with open(filepath) as f:
        trades = json.load(f)

    by_window = defaultdict(list)
    for t in trades:
        by_window[t["slug"]].append({
            "ts": t["timestamp"],
            "side": t["outcome"].lower(),
            "price": t["price"],
            "size": t["size"],
            "usdc_size": t["usdcSize"],
        })

    for slug in by_window:
        by_window[slug].sort(key=lambda x: x["ts"])

    print(f"Loaded {len(trades):,} fills across {len(by_window):,} windows")
    return dict(by_window)


def load_price_log(filepath: str) -> dict:
    """Load price log for binary-searchable market state lookup."""
    windows = defaultdict(lambda: {"ts": [], "yes": [], "no": []})

    with open(filepath) as f:
        reader = csv.DictReader(f)
        for row in reader:
            slug = row.get("market_id", "")
            try:
                dt = datetime.fromisoformat(row["timestamp"])
                ts = dt.replace(tzinfo=timezone.utc).timestamp()
                yes = float(row["yes_price"])
                no = float(row["no_price"])

                windows[slug]["ts"].append(ts)
                windows[slug]["yes"].append(yes)
                windows[slug]["no"].append(no)
            except (ValueError, KeyError):
                continue

    # Sort and filter
    result = {}
    for slug, data in windows.items():
        if len(data["ts"]) < 10:
            continue
        indices = sorted(range(len(data["ts"])), key=lambda i: data["ts"][i])
        result[slug] = {
            "ts": [data["ts"][i] for i in indices],
            "yes": [data["yes"][i] for i in indices],
            "no": [data["no"][i] for i in indices],
        }

    print(f"Loaded price data for {len(result):,} windows")
    return result


# ── Market State Lookup ───────────────────────────────────────────────

def get_price_at_time(prices: dict, target_ts: float,
                      max_diff: float = 5.0) -> tuple:
    """Binary search for closest price observation to a target timestamp."""
    ts_list = prices["ts"]
    idx = bisect_left(ts_list, target_ts)

    best_idx, best_diff = None, float("inf")
    for candidate in [idx - 1, idx]:
        if 0 <= candidate < len(ts_list):
            diff = abs(ts_list[candidate] - target_ts)
            if diff < best_diff:
                best_diff = diff
                best_idx = candidate

    if best_idx is None or best_diff > max_diff:
        return None, None
    return prices["yes"][best_idx], prices["no"][best_idx]


def get_momentum(prices: dict, ts: float, lookback: float) -> Optional[float]:
    """Price change over lookback period (causal — uses only past data)."""
    current, _ = get_price_at_time(prices, ts)
    past, _ = get_price_at_time(prices, ts - lookback, max_diff=lookback)
    if current is None or past is None:
        return None
    return current - past


def get_volatility(prices: dict, ts: float, lookback: float) -> Optional[float]:
    """Realized volatility over lookback period."""
    ts_list = prices["ts"]
    end_idx = bisect_left(ts_list, ts)
    start_idx = bisect_left(ts_list, ts - lookback)

    if end_idx - start_idx < 3:
        return None

    changes = [prices["yes"][i] - prices["yes"][i - 1]
               for i in range(start_idx + 1, min(end_idx + 1, len(ts_list)))]

    return stdev(changes) if len(changes) >= 2 else None


def get_outcome(prices: dict) -> Optional[str]:
    """Determine UP/DOWN from final settlement prices."""
    if not prices["yes"]:
        return None
    return "UP" if prices["yes"][-1] >= 0.95 else (
        "DOWN" if prices["no"][-1] >= 0.95 else None
    )


# ── Feature Extraction ────────────────────────────────────────────────

def extract_fill_features(fills: dict, prices: dict) -> list:
    """
    Build per-fill feature matrix with market state at each fill.

    For each fill, captures:
    - Fill characteristics (size, price, edge vs market)
    - Market state (spread, skew, momentum, volatility)
    - Position state (running inventory, imbalance, unmatched shares)
    - Timing (seconds remaining, % elapsed)
    """
    features = []
    overlapping = sorted(set(fills.keys()) & set(prices.keys()))
    print(f"Processing {len(overlapping)} overlapping windows...")

    for slug in overlapping:
        window_fills = fills[slug]
        window_prices = prices[slug]
        window_start = int(slug.split("-")[-1])
        window_end = window_start + 900
        outcome = get_outcome(window_prices)

        if outcome is None:
            continue

        # Running position state
        up_shares = down_shares = 0
        up_cost = down_cost = 0.0
        fill_count = 0

        for t in window_fills:
            market_yes, market_no = get_price_at_time(
                window_prices, t["ts"], max_diff=5.0)
            if market_yes is None:
                # Update position even without price data
                if t["side"] == "up":
                    up_shares += t["size"]
                    up_cost += t["size"] * t["price"]
                else:
                    down_shares += t["size"]
                    down_cost += t["size"] * t["price"]
                fill_count += 1
                continue

            # Edge: how much better than market did they fill?
            market_price = market_yes if t["side"] == "up" else market_no
            edge = market_price - t["price"]
            is_aggressive = 1 if edge <= 0 else 0

            # Position state BEFORE this fill
            total = up_shares + down_shares
            balance = up_shares / total if total > 0 else 0.5
            imbalance = abs(balance - 0.5)

            features.append({
                "slug": slug,
                "outcome": outcome,
                "trade_side": t["side"],
                "trade_size": t["size"],
                "fill_price": t["price"],
                "market_price": round(market_price, 4),
                "edge": round(edge, 4),
                "is_aggressive": is_aggressive,
                "spread": round(market_yes + market_no - 1.0, 4),
                "price_skew": round(market_yes - market_no, 4),
                "balance": round(balance, 4),
                "imbalance": round(imbalance, 4),
                "fills_so_far": fill_count,
                "unmatched_shares": abs(up_shares - down_shares),
                "secs_remaining": round(window_end - t["ts"], 1),
                "pct_elapsed": round((t["ts"] - window_start) / 900.0, 4),
            })

            # Update position AFTER recording features
            if t["side"] == "up":
                up_shares += t["size"]
                up_cost += t["size"] * t["price"]
            else:
                down_shares += t["size"]
                down_cost += t["size"] * t["price"]
            fill_count += 1

    print(f"Extracted {len(features):,} fill-level features")
    return features


# ── Analysis Functions ────────────────────────────────────────────────

def analyze_aggression_triggers(features: list):
    """
    When does the market maker switch from passive to aggressive?

    Compares market state (imbalance, time remaining, spread) between
    passive fills (positive edge) and aggressive fills (negative edge).

    This reveals the decision boundary of their inventory management.
    """
    passive = [f for f in features if not f["is_aggressive"]]
    aggressive = [f for f in features if f["is_aggressive"]]

    print(f"\n{'=' * 70}")
    print("AGGRESSION TRIGGER ANALYSIS")
    print(f"{'=' * 70}")
    print(f"Passive fills (edge > 0): {len(passive):,} "
          f"({len(passive)/len(features)*100:.1f}%)")
    print(f"Aggressive fills (edge <= 0): {len(aggressive):,} "
          f"({len(aggressive)/len(features)*100:.1f}%)")

    metrics = [
        ("imbalance", "Position imbalance"),
        ("secs_remaining", "Seconds remaining"),
        ("pct_elapsed", "% window elapsed"),
        ("unmatched_shares", "Unmatched shares"),
        ("spread", "Market spread"),
    ]

    print(f"\n{'Feature':<25} {'Passive':>12} {'Aggressive':>12} {'Delta':>10}")
    print("-" * 60)
    for key, label in metrics:
        p_vals = [f[key] for f in passive if f[key] is not None]
        a_vals = [f[key] for f in aggressive if f[key] is not None]
        if p_vals and a_vals:
            delta = mean(a_vals) - mean(p_vals)
            print(f"{label:<25} {mean(p_vals):>12.3f} "
                  f"{mean(a_vals):>12.3f} {delta:>+10.3f}")


def analyze_selection_bias(fills: dict, prices: dict):
    """
    Does the market maker selectively skip certain windows?

    If yes, this reveals which market conditions they consider untradeable.
    Uses only CAUSAL features (observable before the window starts).

    Key question: Is skipping correlated with higher volatility,
    extreme opening prices, or specific hours of day?
    """
    all_windows = set(prices.keys())
    traded_windows = set(fills.keys())
    skipped = all_windows - traded_windows

    print(f"\n{'=' * 70}")
    print("SELECTION BIAS ANALYSIS")
    print(f"{'=' * 70}")
    print(f"Total windows with price data: {len(all_windows):,}")
    print(f"Windows traded: {len(traded_windows & all_windows):,}")
    print(f"Windows skipped: {len(skipped):,}")
    print(f"Skip rate: {len(skipped)/len(all_windows)*100:.1f}%")

    # Compare outcomes
    for label, window_set in [("Traded", traded_windows & all_windows),
                               ("Skipped", skipped)]:
        outcomes = defaultdict(int)
        for slug in window_set:
            o = get_outcome(prices[slug])
            outcomes[o or "UNKNOWN"] += 1
        total = sum(outcomes.values())
        print(f"\n{label} outcomes:")
        for k, v in sorted(outcomes.items()):
            print(f"  {k}: {v} ({v/total*100:.1f}%)")


def analyze_window_outcomes(features: list):
    """
    Aggregate to window level: what distinguishes winning from losing windows?

    Compares fill patterns (aggression %, fill count, entry timing, balance)
    between windows that ended profitably vs unprofitably.
    """
    by_window = defaultdict(list)
    for f in features:
        by_window[f["slug"]].append(f)

    stats = []
    for slug, window_fills in by_window.items():
        first, last = window_fills[0], window_fills[-1]
        n_agg = sum(1 for f in window_fills if f["is_aggressive"])

        up_shares = sum(f["trade_size"] for f in window_fills
                        if f["trade_side"] == "up")
        down_shares = sum(f["trade_size"] for f in window_fills
                          if f["trade_side"] == "down")
        total_cost = sum(f["trade_size"] * f["fill_price"]
                         for f in window_fills)

        payout = up_shares if first["outcome"] == "UP" else down_shares
        pnl = payout - total_cost

        stats.append({
            "slug": slug,
            "n_fills": len(window_fills),
            "agg_pct": n_agg / len(window_fills),
            "entry_secs": first["pct_elapsed"],
            "exit_secs": last["pct_elapsed"],
            "balance": up_shares / (up_shares + down_shares)
                       if (up_shares + down_shares) > 0 else 0.5,
            "pnl": pnl,
            "win": 1 if pnl > 0 else 0,
        })

    wins = [s for s in stats if s["win"]]
    losses = [s for s in stats if not s["win"]]

    print(f"\n{'=' * 70}")
    print("WINDOW-LEVEL OUTCOME ANALYSIS")
    print(f"{'=' * 70}")
    print(f"Windows: {len(stats)} | Wins: {len(wins)} | "
          f"Losses: {len(losses)} | WR: {len(wins)/len(stats)*100:.1f}%")

    metrics = [
        ("n_fills", "Fill count"),
        ("agg_pct", "Aggressive %"),
        ("entry_secs", "Entry timing (% elapsed)"),
        ("balance", "Final UP/total balance"),
    ]

    print(f"\n{'Metric':<25} {'Wins':>12} {'Losses':>12} {'Delta':>10}")
    print("-" * 60)
    for key, label in metrics:
        w = mean([s[key] for s in wins]) if wins else 0
        l = mean([s[key] for s in losses]) if losses else 0
        print(f"{label:<25} {w:>12.4f} {l:>12.4f} {w - l:>+10.4f}")


def main():
    fills_path = os.environ.get(
        "FILLS_FILE", "data/trades.json")
    prices_path = os.environ.get(
        "PRICE_LOG", "data/price_log.csv")

    fills = load_fills(fills_path)
    prices = load_price_log(prices_path)

    # Selection bias (fast, run first)
    analyze_selection_bias(fills, prices)

    # Per-fill feature extraction
    features = extract_fill_features(fills, prices)
    if not features:
        print("No features extracted!")
        return

    # Analysis
    analyze_aggression_triggers(features)
    analyze_window_outcomes(features)

    # Summary
    agg = [f for f in features if f["is_aggressive"]]
    print(f"\n{'=' * 70}")
    print("EXECUTIVE SUMMARY")
    print(f"{'=' * 70}")
    print(f"Total fills analyzed: {len(features):,}")
    print(f"Aggressive fills: {len(agg):,} ({len(agg)/len(features)*100:.1f}%)")

    if agg:
        imbalances = [f["imbalance"] for f in agg]
        times = [f["pct_elapsed"] for f in agg]
        print(f"\nAggressive trigger thresholds (median):")
        print(f"  Position imbalance: {median(imbalances):.1%}")
        print(f"  Window elapsed: {median(times):.1%}")


if __name__ == "__main__":
    main()
