#!/usr/bin/env python3
"""
L2-Backed Orderbook Analysis for Polymarket Market Maker Study

Generates Tier B plots (07-12) — six multi-panel visualizations that use
L2 orderbook snapshots to analyze market maker behavior beyond what raw
trade data alone can reveal.

Methodology:
    For each market window with both fill history and L2 data:
    1. Load L2 book snapshots (full depth at each price level, ~1s intervals)
    2. Build per-asset timelines mapping timestamp -> (bids, asks)
    3. For each fill, binary-search the timeline for before/after snapshots
    4. Classify fills as maker (passive) or taker (aggressive) by comparing
       fill price to the best bid/offer at the time of execution
    5. Extract book depth, spread, microprice, and imbalance features
    6. Aggregate across all windows and generate analysis plots

    Maker/taker classification uses the L2 BBO comparison method:
    - BUY at or above best ask = taker (crossing the spread)
    - BUY below best ask = maker (resting order was filled)
    - SELL at or below best bid = taker (crossing the spread)
    - SELL above best bid = maker (resting order was filled)

    This is more accurate than the vanished-quantity method for aggregate
    statistics because it does not require exact size matching.

Data requirements:
    - L2 orderbook snapshots (JSONL.gz per window, captured via WebSocket)
    - Wallet fill history (JSON, from Polymarket data API)

Plot inventory:
    07. Maker/taker classification breakdown
    08. Book depth around fills (pre/post snapshots)
    09. Ladder reconstruction from maker fill patterns
    10. Spread and depth dynamics over window lifecycle
    11. Aggression triggers backed by L2 context
    12. Book imbalance as a predictive signal

Note: All analysis uses publicly visible on-chain and orderbook data.
      No proprietary strategy parameters are included.
"""

import gzip
import json
import os
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from collections import defaultdict, Counter
from bisect import bisect_right
from statistics import mean, median


# -- Configuration -----------------------------------------------------------
L2_DIR = os.environ.get("L2_DATA_DIR", "data/l2")
TRADES_FILE = os.environ.get("TRADES_FILE", "data/trades.json")
OUTDIR = os.environ.get("PLOT_DIR", "figures")
os.makedirs(OUTDIR, exist_ok=True)

MIN_WINDOW_DURATION = 850   # seconds -- skip truncated captures
MAX_BOOK_GAP = 5.0          # seconds -- max gap between snapshot and fill

# Colors
CLR_MAKER = "#1f77b4"       # blue
CLR_TAKER = "#ff7f0e"       # orange
CLR_BID = "#2ca02c"         # green
CLR_ASK = "#d62728"         # red
CLR_NEUTRAL = "#7f7f7f"     # gray


# ============================================================================
# L2 UTILITY FUNCTIONS
# ============================================================================

def load_trades(filepath: str) -> dict:
    """Load wallet fill history, grouped by market window slug."""
    with open(filepath) as f:
        all_trades = json.load(f)

    by_slug = defaultdict(list)
    for t in all_trades:
        by_slug[t["slug"]].append(t)

    for slug in by_slug:
        by_slug[slug].sort(key=lambda x: x["timestamp"])

    print(f"Loaded {len(all_trades):,} fills across {len(by_slug):,} windows")
    return dict(by_slug)


def load_l2_events(slug: str):
    """Load L2 orderbook events for a single market window."""
    path = os.path.join(L2_DIR, f"{slug}.jsonl.gz")
    if not os.path.exists(path):
        return None
    events = []
    try:
        with gzip.open(path, "rt") as f:
            for line in f:
                events.append(json.loads(line))
    except EOFError:
        pass  # truncated capture -- use what we have
    return events if events else None


def build_book_timeline(events, asset):
    """Build timeline of full book states for one asset (up/dn)."""
    timeline = []
    for ev in events:
        if ev["asset"] != asset or ev["event"] != "book":
            continue
        bids = {round(b[0], 2): b[1] for b in ev.get("bids", [])}
        asks = {round(a[0], 2): a[1] for a in ev.get("asks", [])}
        timeline.append((ev["ts"], bids, asks))
    return timeline


def find_book_around(timeline, fill_ts):
    """Binary search for book snapshots immediately before and after a fill."""
    timestamps = [t[0] for t in timeline]
    idx = bisect_right(timestamps, fill_ts)

    before = timeline[idx - 1] if idx > 0 else None
    after = timeline[idx] if idx < len(timeline) else None

    if before and (fill_ts - before[0]) > MAX_BOOK_GAP:
        before = None
    if after and (after[0] - fill_ts) > MAX_BOOK_GAP:
        after = None

    return before, after


def get_best_bid(bids):
    """Best (highest) bid price."""
    return max(bids.keys()) if bids else 0.0


def get_best_ask(asks):
    """Best (lowest) ask price."""
    return min(asks.keys()) if asks else 1.0


def compute_mid(bids, asks):
    """Midpoint of best bid and best ask."""
    return round((get_best_bid(bids) + get_best_ask(asks)) / 2, 4)


def compute_microprice(bids, asks):
    """Volume-weighted midpoint using BBO depths."""
    bb = get_best_bid(bids)
    ba = get_best_ask(asks)
    bid_sz = bids.get(bb, 0)
    ask_sz = asks.get(ba, 0)
    total = bid_sz + ask_sz
    if total == 0:
        return round((bb + ba) / 2, 4)
    return round((bb * ask_sz + ba * bid_sz) / total, 4)


def compute_spread(bids, asks):
    """Spread in price units."""
    return round(get_best_ask(asks) - get_best_bid(bids), 4)


def total_depth(book, levels=5):
    """Sum depth across top N levels of one side."""
    if not book:
        return 0.0
    prices = sorted(book.keys(), reverse=True)[:levels]  # works for bids
    return sum(book[p] for p in prices)


def bid_depth(bids, levels=5):
    """Total size on top N bid levels."""
    if not bids:
        return 0.0
    top = sorted(bids.keys(), reverse=True)[:levels]
    return sum(bids[p] for p in top)


def ask_depth(asks, levels=5):
    """Total size on top N ask levels."""
    if not asks:
        return 0.0
    top = sorted(asks.keys())[:levels]
    return sum(asks[p] for p in top)


def classify_fill(fill_side, fill_price, before_bids, before_asks):
    """Classify fill as maker/taker using L2 BBO comparison."""
    bb = get_best_bid(before_bids)
    ba = get_best_ask(before_asks)
    if fill_side == "BUY":
        return "taker" if fill_price >= ba else "maker"
    else:
        return "taker" if fill_price <= bb else "maker"


def compute_ofi(before_bids, before_asks, after_bids, after_asks):
    """Order flow imbalance: change in bid depth minus change in ask depth."""
    bd_before = bid_depth(before_bids)
    bd_after = bid_depth(after_bids)
    ad_before = ask_depth(before_asks)
    ad_after = ask_depth(after_asks)
    return (bd_after - bd_before) - (ad_after - ad_before)


# ============================================================================
# WINDOW ANALYSIS
# ============================================================================

def analyze_window(slug, trades, events):
    """
    Process all fills in a single market window.

    For each fill, extract:
    - Maker/taker classification
    - Book depth at fill price (before/after)
    - Spread and microprice at time of fill
    - Book imbalance metrics
    - Timing within window
    """
    up_timeline = build_book_timeline(events, "up")
    dn_timeline = build_book_timeline(events, "dn")

    window_start = events[0]["ts"]
    window_end = events[-1]["ts"]
    window_dur = window_end - window_start

    results = []
    for trade in trades:
        asset = "up" if trade["outcome"] == "Up" else "dn"
        timeline = up_timeline if asset == "up" else dn_timeline

        if not timeline:
            continue

        before, after = find_book_around(timeline, trade["timestamp"])
        if before is None or after is None:
            continue

        _, before_bids, before_asks = before
        _, after_bids, after_asks = after
        fill_price = round(trade["price"], 2)
        fill_side = trade["side"]

        # Classification
        mt = classify_fill(fill_side, fill_price, before_bids, before_asks)

        # Book depth at fill price
        pre_ask_at_fill = before_asks.get(fill_price, 0)
        post_ask_at_fill = after_asks.get(fill_price, 0)
        pre_bid_at_fill = before_bids.get(fill_price, 0)
        post_bid_at_fill = after_bids.get(fill_price, 0)

        # Vanished quantity
        if fill_side == "BUY":
            vanished = pre_ask_at_fill - post_ask_at_fill
        else:
            vanished = pre_bid_at_fill - post_bid_at_fill

        # Spread and microprice
        spread = compute_spread(before_bids, before_asks)
        mid = compute_mid(before_bids, before_asks)
        microprice = compute_microprice(before_bids, before_asks)

        # BBO values
        bb = get_best_bid(before_bids)
        ba = get_best_ask(before_asks)

        # Depth
        bd = bid_depth(before_bids)
        ad = ask_depth(before_asks)
        total_bbo = bd + ad
        imbalance = (bd - ad) / total_bbo if total_bbo > 0 else 0.0

        # OFI
        ofi = compute_ofi(before_bids, before_asks, after_bids, after_asks)

        # Timing
        elapsed = trade["timestamp"] - window_start
        pct_elapsed = elapsed / window_dur if window_dur > 0 else 0.0

        results.append({
            "slug": slug,
            "ts": trade["timestamp"],
            "asset": asset,
            "fill_side": fill_side,
            "fill_price": fill_price,
            "fill_size": trade["size"],
            "type": mt,
            "pre_ask_at_fill": pre_ask_at_fill,
            "post_ask_at_fill": post_ask_at_fill,
            "pre_bid_at_fill": pre_bid_at_fill,
            "post_bid_at_fill": post_bid_at_fill,
            "vanished": vanished,
            "vanished_ratio": vanished / max(trade["size"], 0.01),
            "spread": spread,
            "mid": mid,
            "microprice": microprice,
            "bb": bb,
            "ba": ba,
            "bid_depth": bd,
            "ask_depth": ad,
            "imbalance": imbalance,
            "ofi": ofi,
            "elapsed": elapsed,
            "pct_elapsed": pct_elapsed,
        })

    return results


def build_timeline_features(events, asset):
    """
    Build time-series features from L2 snapshots for lifecycle plots.

    Returns list of dicts with spread, depth, microprice at each snapshot.
    """
    timeline = build_book_timeline(events, asset)
    if not timeline or len(timeline) < 2:
        return []

    t0 = timeline[0][0]
    t_end = timeline[-1][0]
    dur = t_end - t0

    features = []
    for ts, bids, asks in timeline:
        if not bids or not asks:
            continue
        features.append({
            "pct": (ts - t0) / dur if dur > 0 else 0,
            "spread": compute_spread(bids, asks),
            "mid": compute_mid(bids, asks),
            "microprice": compute_microprice(bids, asks),
            "bid_depth": bid_depth(bids),
            "ask_depth": ask_depth(asks),
            "bb": get_best_bid(bids),
            "ba": get_best_ask(asks),
        })
    return features


# ============================================================================
# PLOT 07: MAKER / TAKER CLASSIFICATION
# ============================================================================

def plot_07_maker_taker(fills):
    """
    07: Maker vs taker classification breakdown.

    (a) Overall maker/taker pie chart
    (b) Maker vs taker ratio by time bucket
    (c) Maker vs taker by imbalance level
    (d) Vanished-to-fill ratio histogram
    """
    print("\nPlot 07: Maker/taker classification...")
    makers = [f for f in fills if f["type"] == "maker"]
    takers = [f for f in fills if f["type"] == "taker"]
    n_total = len(fills)

    fig, axes = plt.subplots(2, 2, figsize=(14, 10))

    # (a) Pie chart
    ax = axes[0, 0]
    counts = [len(makers), len(takers)]
    labels = [f"Maker ({len(makers):,})", f"Taker ({len(takers):,})"]
    ax.pie(counts, labels=labels, colors=[CLR_MAKER, CLR_TAKER],
           autopct='%1.1f%%', startangle=90, textprops={'fontsize': 10})
    ax.set_title(f"Overall Maker/Taker Split (n={n_total:,} fills)")

    # (b) Ratio by time bucket (0-3, 3-6, 6-9, 9-12, 12-15 min)
    ax = axes[0, 1]
    time_edges = [0, 180, 360, 540, 720, 900]
    time_labels = ["0-3m", "3-6m", "6-9m", "9-12m", "12-15m"]
    maker_counts_t = []
    taker_counts_t = []
    for i in range(len(time_edges) - 1):
        lo, hi = time_edges[i], time_edges[i + 1]
        m = sum(1 for f in makers if lo <= f["elapsed"] < hi)
        t = sum(1 for f in takers if lo <= f["elapsed"] < hi)
        maker_counts_t.append(m)
        taker_counts_t.append(t)

    x = np.arange(len(time_labels))
    width = 0.35
    ax.bar(x - width / 2, maker_counts_t, width, color=CLR_MAKER, label="Maker")
    ax.bar(x + width / 2, taker_counts_t, width, color=CLR_TAKER, label="Taker")
    ax.set_xticks(x)
    ax.set_xticklabels(time_labels)
    ax.set_ylabel("# fills")
    ax.set_title("Maker vs Taker by Time Bucket")
    ax.legend()

    # (c) By imbalance level
    ax = axes[1, 0]
    imb_edges = [0.0, 0.05, 0.10, 0.15, 0.20, 1.0]
    imb_labels = ["0-5%", "5-10%", "10-15%", "15-20%", "20%+"]
    maker_counts_i = []
    taker_counts_i = []
    for i in range(len(imb_edges) - 1):
        lo, hi = imb_edges[i], imb_edges[i + 1]
        m = sum(1 for f in makers if lo <= abs(f["imbalance"]) < hi)
        t = sum(1 for f in takers if lo <= abs(f["imbalance"]) < hi)
        maker_counts_i.append(m)
        taker_counts_i.append(t)

    x = np.arange(len(imb_labels))
    ax.bar(x - width / 2, maker_counts_i, width, color=CLR_MAKER, label="Maker")
    ax.bar(x + width / 2, taker_counts_i, width, color=CLR_TAKER, label="Taker")
    ax.set_xticks(x)
    ax.set_xticklabels(imb_labels)
    ax.set_ylabel("# fills")
    ax.set_title("Maker vs Taker by Book Imbalance Level")
    ax.legend()

    # (d) Vanished-to-fill ratio histogram
    ax = axes[1, 1]
    ratios = [f["vanished_ratio"] for f in fills if f["vanished_ratio"] > 0]
    if ratios:
        clipped = [min(r, 3.0) for r in ratios]
        ax.hist(clipped, bins=60, color=CLR_NEUTRAL, edgecolor="white", alpha=0.8)
        ax.axvline(1.0, color="red", linestyle="--", linewidth=1.5,
                   label="Exact match (1.0)")
        if len(ratios) > 0:
            med = median(ratios)
            ax.axvline(med, color="black", linestyle="--",
                       label=f"Median: {med:.2f}")
        ax.set_xlabel("Vanished / fill size")
        ax.set_ylabel("# fills")
        ax.set_title(f"Vanished-to-Fill Ratio (n={len(ratios):,})")
        ax.legend()

    plt.suptitle(f"Plot 07: Maker/Taker Classification (n={n_total:,} fills)",
                 fontsize=13, fontweight="bold", y=1.01)
    plt.tight_layout()
    path = os.path.join(OUTDIR, "07_maker_taker_classification.png")
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  Saved: {path}")


# ============================================================================
# PLOT 08: BOOK DEPTH AROUND FILLS
# ============================================================================

def plot_08_book_depth(fills):
    """
    08: Pre/post book depth at the fill price level.

    (a) Pre-fill ask depth for taker fills
    (b) Post-fill ask depth for taker fills
    (c) Pre-fill bid depth for maker fills
    (d) Post-fill bid depth for maker fills
    """
    print("\nPlot 08: Book depth around fills...")
    takers = [f for f in fills if f["type"] == "taker"]
    makers = [f for f in fills if f["type"] == "maker"]

    fig, axes = plt.subplots(2, 2, figsize=(14, 10))

    # (a) Pre-fill ask depth at fill price — taker fills
    ax = axes[0, 0]
    vals = [f["pre_ask_at_fill"] for f in takers if f["pre_ask_at_fill"] > 0]
    if vals:
        clipped = [min(v, np.percentile(vals, 99)) for v in vals]
        ax.hist(clipped, bins=60, color=CLR_TAKER, edgecolor="white", alpha=0.8)
        ax.axvline(median(vals), color="black", linestyle="--",
                   label=f"Median: {median(vals):.0f}")
        ax.set_xlabel("Ask depth at fill price (shares)")
        ax.set_ylabel("# fills")
        ax.set_title(f"(a) Pre-Fill Ask Depth — Taker Fills (n={len(vals):,})")
        ax.legend()

    # (b) Post-fill ask depth at fill price — taker fills
    ax = axes[0, 1]
    vals = [f["post_ask_at_fill"] for f in takers]
    if vals:
        clipped = [min(v, max(np.percentile(vals, 99), 1)) for v in vals]
        ax.hist(clipped, bins=60, color=CLR_TAKER, edgecolor="white", alpha=0.6)
        zero_pct = sum(1 for v in vals if v == 0) / len(vals) * 100
        ax.set_xlabel("Ask depth at fill price (shares)")
        ax.set_ylabel("# fills")
        ax.set_title(f"(b) Post-Fill Ask Depth — Taker ({zero_pct:.0f}% swept to zero)")

    # (c) Pre-fill bid depth at fill price — maker fills
    ax = axes[1, 0]
    vals = [f["pre_bid_at_fill"] for f in makers if f["pre_bid_at_fill"] > 0]
    if vals:
        clipped = [min(v, np.percentile(vals, 99)) for v in vals]
        ax.hist(clipped, bins=60, color=CLR_MAKER, edgecolor="white", alpha=0.8)
        ax.axvline(median(vals), color="black", linestyle="--",
                   label=f"Median: {median(vals):.0f}")
        ax.set_xlabel("Bid depth at fill price (shares)")
        ax.set_ylabel("# fills")
        ax.set_title(f"(c) Pre-Fill Bid Depth — Maker Fills (n={len(vals):,})")
        ax.legend()

    # (d) Post-fill bid depth at fill price — maker fills
    ax = axes[1, 1]
    vals = [f["post_bid_at_fill"] for f in makers]
    if vals:
        clipped = [min(v, max(np.percentile(vals, 99), 1)) for v in vals]
        ax.hist(clipped, bins=60, color=CLR_MAKER, edgecolor="white", alpha=0.6)
        zero_pct = sum(1 for v in vals if v == 0) / len(vals) * 100
        ax.set_xlabel("Bid depth at fill price (shares)")
        ax.set_ylabel("# fills")
        ax.set_title(f"(d) Post-Fill Bid Depth — Maker ({zero_pct:.0f}% swept to zero)")

    plt.suptitle(f"Plot 08: Book Depth Around Fills (n={len(fills):,} total)",
                 fontsize=13, fontweight="bold", y=1.01)
    plt.tight_layout()
    path = os.path.join(OUTDIR, "08_book_depth_around_fills.png")
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  Saved: {path}")


# ============================================================================
# PLOT 09: LADDER RECONSTRUCTION
# ============================================================================

def plot_09_ladder(fills):
    """
    09: Reconstruct ladder structure from maker fill patterns.

    (a) Level spacing histogram (cents between adjacent maker fill levels)
    (b) Mean fill size per level
    (c) Active levels per side distribution
    (d) Ladder offset from mid price
    """
    print("\nPlot 09: Ladder reconstruction...")
    makers = [f for f in fills if f["type"] == "maker"]

    fig, axes = plt.subplots(2, 2, figsize=(14, 10))

    # Group maker fills by window and asset to reconstruct ladders
    by_window_asset = defaultdict(list)
    for f in makers:
        key = (f["slug"], f["asset"])
        by_window_asset[key].append(f)

    all_spacings = []
    sizes_by_level_offset = defaultdict(list)
    levels_per_side = []
    offsets_from_mid = []

    for (slug, asset), window_fills in by_window_asset.items():
        prices = sorted(set(f["fill_price"] for f in window_fills))
        if len(prices) < 2:
            continue

        # Level spacing
        spacings = [round(prices[i + 1] - prices[i], 2) for i in range(len(prices) - 1)]
        all_spacings.extend(spacings)

        # Active levels
        levels_per_side.append(len(prices))

        # Size per level and offset from mid
        for f in window_fills:
            mid = f["mid"]
            offset = round(f["fill_price"] - mid, 4)
            offsets_from_mid.append(offset)
            # Bin by level index (0 = closest to mid)
            idx = prices.index(f["fill_price"])
            sizes_by_level_offset[idx].append(f["fill_size"])

    # (a) Level spacing histogram
    ax = axes[0, 0]
    if all_spacings:
        cents = [s * 100 for s in all_spacings]
        clipped = [min(c, 10) for c in cents]
        ax.hist(clipped, bins=50, color=CLR_MAKER, edgecolor="white", alpha=0.8)
        ax.axvline(median(cents), color="black", linestyle="--",
                   label=f"Median: {median(cents):.1f}c")
        ax.set_xlabel("Level spacing (cents)")
        ax.set_ylabel("# observations")
        ax.set_title(f"(a) Spacing Between Adjacent Maker Levels (n={len(all_spacings):,})")
        ax.legend()

    # (b) Mean fill size per level index
    ax = axes[0, 1]
    max_levels = min(10, max(sizes_by_level_offset.keys()) + 1) if sizes_by_level_offset else 1
    level_indices = list(range(max_levels))
    mean_sizes = [np.mean(sizes_by_level_offset[i]) if i in sizes_by_level_offset else 0
                  for i in level_indices]
    counts_per = [len(sizes_by_level_offset[i]) if i in sizes_by_level_offset else 0
                  for i in level_indices]
    ax.bar(level_indices, mean_sizes, color=CLR_MAKER, edgecolor="white", alpha=0.8)
    for i, (ms, ct) in enumerate(zip(mean_sizes, counts_per)):
        if ct > 0:
            ax.text(i, ms + 0.5, f"n={ct}", ha="center", fontsize=7)
    ax.set_xlabel("Level index (0 = closest to mid)")
    ax.set_ylabel("Mean fill size (shares)")
    ax.set_title("(b) Mean Fill Size Per Ladder Level")

    # (c) Active levels per side
    ax = axes[1, 0]
    if levels_per_side:
        ax.hist(levels_per_side, bins=range(1, max(levels_per_side) + 2),
                color=CLR_MAKER, edgecolor="white", alpha=0.8, align="left")
        ax.axvline(median(levels_per_side), color="black", linestyle="--",
                   label=f"Median: {median(levels_per_side):.0f}")
        ax.set_xlabel("# active price levels")
        ax.set_ylabel("# (window, asset) pairs")
        ax.set_title(f"(c) Active Levels Per Side (n={len(levels_per_side):,} windows)")
        ax.legend()

    # (d) Ladder offset from mid
    ax = axes[1, 1]
    if offsets_from_mid:
        cents = [o * 100 for o in offsets_from_mid]
        clipped = [max(-15, min(15, c)) for c in cents]
        ax.hist(clipped, bins=60, color=CLR_MAKER, edgecolor="white", alpha=0.8)
        ax.axvline(0, color="red", linestyle="--", linewidth=1.5, label="Mid price")
        ax.axvline(median(cents), color="black", linestyle="--",
                   label=f"Median: {median(cents):.2f}c")
        ax.set_xlabel("Offset from mid (cents)")
        ax.set_ylabel("# fills")
        ax.set_title(f"(d) Maker Fill Offset from Mid (n={len(offsets_from_mid):,})")
        ax.legend()

    plt.suptitle(f"Plot 09: Ladder Reconstruction (n={len(makers):,} maker fills)",
                 fontsize=13, fontweight="bold", y=1.01)
    plt.tight_layout()
    path = os.path.join(OUTDIR, "09_ladder_reconstruction.png")
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  Saved: {path}")


# ============================================================================
# PLOT 10: SPREAD AND DEPTH DYNAMICS
# ============================================================================

def plot_10_spread_depth(all_features):
    """
    10: Spread and depth dynamics over window lifecycle.

    all_features: list of per-snapshot feature dicts from build_timeline_features()

    (a) Spread over window lifecycle (30s buckets)
    (b) BBO depth over window lifecycle
    (c) Spread asymmetry (UP spread vs DN spread)
    (d) Microprice vs mid divergence
    """
    print("\nPlot 10: Spread and depth dynamics...")
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))

    n_windows = len(all_features)

    # Flatten and bucket by pct elapsed (30s = ~3.3% of 900s window)
    bucket_size = 1 / 30  # ~30s buckets
    spread_by_bucket = defaultdict(list)
    depth_by_bucket = defaultdict(list)
    micro_div_by_bucket = defaultdict(list)

    up_spreads_by_bucket = defaultdict(list)
    dn_spreads_by_bucket = defaultdict(list)

    for window_feats in all_features:
        asset = window_feats["asset"]
        for feat in window_feats["features"]:
            bucket = round(feat["pct"] / bucket_size) * bucket_size
            bucket = min(bucket, 1.0)
            spread_by_bucket[bucket].append(feat["spread"] * 100)  # cents
            depth_by_bucket[bucket].append(feat["bid_depth"] + feat["ask_depth"])
            micro_div_by_bucket[bucket].append(
                (feat["microprice"] - feat["mid"]) * 100  # cents
            )
            if asset == "up":
                up_spreads_by_bucket[bucket].append(feat["spread"] * 100)
            else:
                dn_spreads_by_bucket[bucket].append(feat["spread"] * 100)

    # (a) Spread over lifecycle
    ax = axes[0, 0]
    buckets_sorted = sorted(spread_by_bucket.keys())
    if buckets_sorted:
        meds = [median(spread_by_bucket[b]) for b in buckets_sorted]
        p25 = [np.percentile(spread_by_bucket[b], 25) for b in buckets_sorted]
        p75 = [np.percentile(spread_by_bucket[b], 75) for b in buckets_sorted]
        ax.fill_between(buckets_sorted, p25, p75, alpha=0.3, color="steelblue")
        ax.plot(buckets_sorted, meds, color="steelblue", linewidth=2, label="Median")
        ax.set_xlabel("% window elapsed")
        ax.set_ylabel("Spread (cents)")
        ax.set_title(f"(a) Spread Over Lifecycle (n={n_windows} windows)")
        ax.legend()
        ax.set_xlim(0, 1)

    # (b) BBO depth over lifecycle
    ax = axes[0, 1]
    if buckets_sorted:
        meds = [median(depth_by_bucket[b]) for b in buckets_sorted]
        p25 = [np.percentile(depth_by_bucket[b], 25) for b in buckets_sorted]
        p75 = [np.percentile(depth_by_bucket[b], 75) for b in buckets_sorted]
        ax.fill_between(buckets_sorted, p25, p75, alpha=0.3, color="green")
        ax.plot(buckets_sorted, meds, color="green", linewidth=2, label="Median")
        ax.set_xlabel("% window elapsed")
        ax.set_ylabel("BBO depth (shares)")
        ax.set_title("(b) BBO Depth Over Lifecycle")
        ax.legend()
        ax.set_xlim(0, 1)

    # (c) Spread asymmetry — UP side vs DN side
    ax = axes[1, 0]
    common_buckets = sorted(set(up_spreads_by_bucket.keys()) &
                            set(dn_spreads_by_bucket.keys()))
    if common_buckets:
        up_meds = [median(up_spreads_by_bucket[b]) for b in common_buckets]
        dn_meds = [median(dn_spreads_by_bucket[b]) for b in common_buckets]
        ax.plot(common_buckets, up_meds, color=CLR_BID, linewidth=2, label="UP asset spread")
        ax.plot(common_buckets, dn_meds, color=CLR_ASK, linewidth=2, label="DN asset spread")
        ax.set_xlabel("% window elapsed")
        ax.set_ylabel("Spread (cents)")
        ax.set_title("(c) Spread Asymmetry: UP vs DN")
        ax.legend()
        ax.set_xlim(0, 1)

    # (d) Microprice vs mid divergence
    ax = axes[1, 1]
    if buckets_sorted:
        meds = [median(micro_div_by_bucket[b]) for b in buckets_sorted]
        p25 = [np.percentile(micro_div_by_bucket[b], 25) for b in buckets_sorted]
        p75 = [np.percentile(micro_div_by_bucket[b], 75) for b in buckets_sorted]
        ax.fill_between(buckets_sorted, p25, p75, alpha=0.3, color="purple")
        ax.plot(buckets_sorted, meds, color="purple", linewidth=2, label="Median")
        ax.axhline(0, color="gray", linestyle="--", alpha=0.5)
        ax.set_xlabel("% window elapsed")
        ax.set_ylabel("Microprice - Mid (cents)")
        ax.set_title("(d) Microprice vs Mid Divergence")
        ax.legend()
        ax.set_xlim(0, 1)

    plt.suptitle(f"Plot 10: Spread & Depth Dynamics (n={n_windows} windows)",
                 fontsize=13, fontweight="bold", y=1.01)
    plt.tight_layout()
    path = os.path.join(OUTDIR, "10_spread_and_depth_dynamics.png")
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  Saved: {path}")


# ============================================================================
# PLOT 11: AGGRESSION TRIGGERS (L2-BACKED)
# ============================================================================

def plot_11_aggression_triggers(fills):
    """
    11: What L2 conditions trigger aggressive (taker) fills?

    (a) Inventory imbalance at taker fills vs maker fills
    (b) Fill price vs L2 BBO at time of fill
    (c) Time elapsed vs taker % (30s buckets)
    (d) Instant pair cost at taker fills
    """
    print("\nPlot 11: Aggression triggers (L2)...")
    makers = [f for f in fills if f["type"] == "maker"]
    takers = [f for f in fills if f["type"] == "taker"]

    fig, axes = plt.subplots(2, 2, figsize=(14, 10))

    # (a) Imbalance at taker fills vs maker fills
    ax = axes[0, 0]
    maker_imb = [abs(f["imbalance"]) for f in makers]
    taker_imb = [abs(f["imbalance"]) for f in takers]
    bins = np.linspace(0, 1, 40)
    if maker_imb:
        ax.hist(maker_imb, bins=bins, color=CLR_MAKER, alpha=0.6,
                label=f"Maker (n={len(maker_imb):,})", density=True)
    if taker_imb:
        ax.hist(taker_imb, bins=bins, color=CLR_TAKER, alpha=0.6,
                label=f"Taker (n={len(taker_imb):,})", density=True)
    ax.set_xlabel("|Book imbalance| at fill")
    ax.set_ylabel("Density")
    ax.set_title("(a) Book Imbalance: Taker vs Maker Fills")
    ax.legend()

    # (b) Fill price vs L2 BBO — distance from best bid/ask
    ax = axes[1, 0]
    buy_fills = [f for f in fills if f["fill_side"] == "BUY"]
    sell_fills = [f for f in fills if f["fill_side"] == "SELL"]

    buy_dist = [(f["fill_price"] - f["ba"]) * 100 for f in buy_fills if f["ba"] > 0]
    sell_dist = [(f["bb"] - f["fill_price"]) * 100 for f in sell_fills if f["bb"] > 0]

    all_dist = buy_dist + sell_dist
    if all_dist:
        clipped = [max(-5, min(5, d)) for d in all_dist]
        colors_dist = ([CLR_BID] * len(buy_dist)) + ([CLR_ASK] * len(sell_dist))
        ax.hist([max(-5, min(5, d)) for d in buy_dist], bins=50,
                color=CLR_BID, alpha=0.6, label=f"BUY vs ask (n={len(buy_dist):,})")
        ax.hist([max(-5, min(5, d)) for d in sell_dist], bins=50,
                color=CLR_ASK, alpha=0.6, label=f"SELL vs bid (n={len(sell_dist):,})")
        ax.axvline(0, color="black", linestyle="--", linewidth=1.5, label="BBO")
        ax.set_xlabel("Distance from BBO (cents, + = crossing)")
        ax.set_ylabel("# fills")
        ax.set_title("(b) Fill Price vs L2 BBO")
        ax.legend(fontsize=8)

    # (c) Taker % by 30s elapsed buckets
    ax = axes[0, 1]
    bucket_seconds = 30
    bucket_size = bucket_seconds / 900.0  # fraction of 15m window
    taker_by_bucket = defaultdict(lambda: [0, 0])  # [taker_count, total_count]
    for f in fills:
        bucket = round(f["pct_elapsed"] / bucket_size) * bucket_size
        bucket = min(bucket, 1.0)
        taker_by_bucket[bucket][1] += 1
        if f["type"] == "taker":
            taker_by_bucket[bucket][0] += 1

    buckets_sorted = sorted(taker_by_bucket.keys())
    taker_pcts = []
    for b in buckets_sorted:
        tc, total = taker_by_bucket[b]
        taker_pcts.append(tc / total * 100 if total > 0 else 0)

    ax.bar(buckets_sorted, taker_pcts, width=bucket_size * 0.8,
           color=CLR_TAKER, alpha=0.8)
    overall_taker_pct = len(takers) / len(fills) * 100 if fills else 0
    ax.axhline(overall_taker_pct, color="black", linestyle="--",
               label=f"Overall: {overall_taker_pct:.1f}%")
    ax.set_xlabel("% window elapsed")
    ax.set_ylabel("Taker fill %")
    ax.set_title("(c) Taker Rate Over Window Lifecycle")
    ax.legend()
    ax.set_xlim(0, 1)

    # (d) Spread at taker fills (proxy for instant pair cost)
    ax = axes[1, 1]
    taker_spreads = [f["spread"] * 100 for f in takers if f["spread"] > 0]
    maker_spreads = [f["spread"] * 100 for f in makers if f["spread"] > 0]
    if taker_spreads:
        ax.hist(taker_spreads, bins=50, range=(0, 10), color=CLR_TAKER,
                alpha=0.6, label=f"Taker (n={len(taker_spreads):,})", density=True)
    if maker_spreads:
        ax.hist(maker_spreads, bins=50, range=(0, 10), color=CLR_MAKER,
                alpha=0.6, label=f"Maker (n={len(maker_spreads):,})", density=True)
    ax.set_xlabel("Spread at fill (cents)")
    ax.set_ylabel("Density")
    ax.set_title("(d) Spread at Fill: Taker vs Maker")
    ax.legend()

    plt.suptitle(f"Plot 11: Aggression Triggers — L2 Context (n={len(fills):,} fills)",
                 fontsize=13, fontweight="bold", y=1.01)
    plt.tight_layout()
    path = os.path.join(OUTDIR, "11_aggression_triggers_l2.png")
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  Saved: {path}")


# ============================================================================
# PLOT 12: BOOK IMBALANCE SIGNAL
# ============================================================================

def plot_12_imbalance_signal(fills):
    """
    12: Does book imbalance predict fill direction?

    (a) Bid/ask depth ratio vs next-fill side
    (b) Microprice lead time
    (c) Depth recovery after sweeps
    (d) OFI vs fill direction
    """
    print("\nPlot 12: Book imbalance signal...")
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))

    # (a) Bid/ask depth ratio vs next-fill side
    ax = axes[0, 0]
    buy_fills = [f for f in fills if f["fill_side"] == "BUY"]
    sell_fills = [f for f in fills if f["fill_side"] == "SELL"]

    buy_ratios = []
    sell_ratios = []
    for f in buy_fills:
        if f["ask_depth"] > 0:
            buy_ratios.append(f["bid_depth"] / f["ask_depth"])
    for f in sell_fills:
        if f["ask_depth"] > 0:
            sell_ratios.append(f["bid_depth"] / f["ask_depth"])

    if buy_ratios and sell_ratios:
        bins = np.linspace(0, 3, 50)
        ax.hist([min(r, 3) for r in buy_ratios], bins=bins, color=CLR_BID,
                alpha=0.6, label=f"Before BUY fill (n={len(buy_ratios):,})",
                density=True)
        ax.hist([min(r, 3) for r in sell_ratios], bins=bins, color=CLR_ASK,
                alpha=0.6, label=f"Before SELL fill (n={len(sell_ratios):,})",
                density=True)
        ax.axvline(1.0, color="black", linestyle="--", label="Balanced")
        ax.set_xlabel("Bid/Ask depth ratio")
        ax.set_ylabel("Density")
        ax.set_title("(a) Book Ratio Before Fill")
        ax.legend(fontsize=8)

    # (b) Microprice lead — does microprice predict fill direction?
    ax = axes[0, 1]
    micro_lead_buy = [(f["microprice"] - f["mid"]) * 100 for f in buy_fills]
    micro_lead_sell = [(f["microprice"] - f["mid"]) * 100 for f in sell_fills]

    if micro_lead_buy and micro_lead_sell:
        bins = np.linspace(-3, 3, 60)
        ax.hist([max(-3, min(3, m)) for m in micro_lead_buy], bins=bins,
                color=CLR_BID, alpha=0.6,
                label=f"Before BUY (n={len(micro_lead_buy):,})", density=True)
        ax.hist([max(-3, min(3, m)) for m in micro_lead_sell], bins=bins,
                color=CLR_ASK, alpha=0.6,
                label=f"Before SELL (n={len(micro_lead_sell):,})", density=True)
        ax.axvline(0, color="black", linestyle="--")
        ax.set_xlabel("Microprice - Mid (cents)")
        ax.set_ylabel("Density")
        ax.set_title("(b) Microprice Lead Before Fill Direction")
        ax.legend(fontsize=8)

    # (c) Depth recovery after sweeps — compare pre/post depth for taker fills
    ax = axes[1, 0]
    taker_fills = [f for f in fills if f["type"] == "taker"]
    if taker_fills:
        # For taker BUY fills: ask side was swept
        buy_takers = [f for f in taker_fills if f["fill_side"] == "BUY"]
        sell_takers = [f for f in taker_fills if f["fill_side"] == "SELL"]

        buy_recovery = [f["post_ask_at_fill"] / max(f["pre_ask_at_fill"], 0.01)
                        for f in buy_takers if f["pre_ask_at_fill"] > 0]
        sell_recovery = [f["post_bid_at_fill"] / max(f["pre_bid_at_fill"], 0.01)
                         for f in sell_takers if f["pre_bid_at_fill"] > 0]

        all_recovery = buy_recovery + sell_recovery
        if all_recovery:
            clipped = [min(r, 2.0) for r in all_recovery]
            ax.hist(clipped, bins=50, color=CLR_TAKER, edgecolor="white", alpha=0.8)
            ax.axvline(1.0, color="red", linestyle="--", label="Full recovery")
            ax.axvline(0.0, color="black", linestyle="--", alpha=0.5, label="Complete sweep")
            med = median(all_recovery)
            ax.axvline(med, color="blue", linestyle="--",
                       label=f"Median: {med:.2f}")
            ax.set_xlabel("Post/Pre depth ratio")
            ax.set_ylabel("# fills")
            ax.set_title(f"(c) Depth Recovery After Sweeps (n={len(all_recovery):,})")
            ax.legend(fontsize=8)

    # (d) OFI vs fill direction
    ax = axes[1, 1]
    buy_ofi = [f["ofi"] for f in buy_fills]
    sell_ofi = [f["ofi"] for f in sell_fills]

    if buy_ofi and sell_ofi:
        p1 = np.percentile(buy_ofi + sell_ofi, 1)
        p99 = np.percentile(buy_ofi + sell_ofi, 99)
        bins = np.linspace(p1, p99, 50)
        ax.hist([max(p1, min(p99, o)) for o in buy_ofi], bins=bins,
                color=CLR_BID, alpha=0.6,
                label=f"BUY fills (n={len(buy_ofi):,})", density=True)
        ax.hist([max(p1, min(p99, o)) for o in sell_ofi], bins=bins,
                color=CLR_ASK, alpha=0.6,
                label=f"SELL fills (n={len(sell_ofi):,})", density=True)
        ax.axvline(0, color="black", linestyle="--")
        ax.set_xlabel("Order Flow Imbalance (OFI)")
        ax.set_ylabel("Density")
        ax.set_title("(d) OFI at Fill Time by Direction")
        ax.legend(fontsize=8)

    plt.suptitle(f"Plot 12: Book Imbalance Signal (n={len(fills):,} fills)",
                 fontsize=13, fontweight="bold", y=1.01)
    plt.tight_layout()
    path = os.path.join(OUTDIR, "12_book_imbalance_signal.png")
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  Saved: {path}")


# ============================================================================
# SUMMARY STATISTICS
# ============================================================================

def print_summary(fills, n_windows_processed, n_windows_skipped):
    """Print summary statistics for the L2 analysis run."""
    makers = [f for f in fills if f["type"] == "maker"]
    takers = [f for f in fills if f["type"] == "taker"]

    print(f"\n{'=' * 70}")
    print("L2 ANALYSIS SUMMARY")
    print(f"{'=' * 70}")
    print(f"Windows processed:     {n_windows_processed:,}")
    print(f"Windows skipped (no L2): {n_windows_skipped:,}")
    print(f"Total classified fills: {len(fills):,}")
    print(f"  Maker (passive):     {len(makers):,} "
          f"({len(makers)/max(len(fills),1)*100:.1f}%)")
    print(f"  Taker (aggressive):  {len(takers):,} "
          f"({len(takers)/max(len(fills),1)*100:.1f}%)")

    if makers:
        maker_sizes = [f["fill_size"] for f in makers]
        print(f"\nMaker fill sizes: "
              f"mean={np.mean(maker_sizes):.1f}, "
              f"median={np.median(maker_sizes):.1f}")

    if takers:
        taker_sizes = [f["fill_size"] for f in takers]
        print(f"Taker fill sizes: "
              f"mean={np.mean(taker_sizes):.1f}, "
              f"median={np.median(taker_sizes):.1f}")

    if fills:
        spreads = [f["spread"] * 100 for f in fills if f["spread"] > 0]
        if spreads:
            print(f"\nSpread at fills: "
                  f"mean={mean(spreads):.2f}c, "
                  f"median={median(spreads):.2f}c")

        imbalances = [abs(f["imbalance"]) for f in fills]
        print(f"Book imbalance at fills: "
              f"mean={mean(imbalances):.3f}, "
              f"median={median(imbalances):.3f}")

        ratios = [f["vanished_ratio"] for f in fills if f["vanished_ratio"] > 0]
        if ratios:
            exact = sum(1 for r in ratios if 0.95 <= r <= 1.05)
            print(f"Vanished/fill exact match: "
                  f"{exact}/{len(ratios)} ({exact/len(ratios)*100:.1f}%)")

    print(f"{'=' * 70}\n")


# ============================================================================
# MAIN
# ============================================================================

def main():
    print("L2-Backed Orderbook Analysis")
    print(f"{'=' * 70}")
    print(f"L2 data dir: {L2_DIR}")
    print(f"Trades file: {TRADES_FILE}")
    print(f"Output dir:  {OUTDIR}")
    print(f"{'=' * 70}\n")

    # Load trades
    trades_by_slug = load_trades(TRADES_FILE)

    # Process each window
    all_fills = []
    all_timeline_features = []
    n_processed = 0
    n_skipped = 0

    for slug in sorted(trades_by_slug.keys()):
        events = load_l2_events(slug)
        if events is None or len(events) < 100:
            n_skipped += 1
            continue

        duration = events[-1]["ts"] - events[0]["ts"]
        if duration < MIN_WINDOW_DURATION:
            n_skipped += 1
            continue

        # Classify fills
        fills = analyze_window(slug, trades_by_slug[slug], events)
        all_fills.extend(fills)

        # Build timeline features for spread/depth plots
        for asset in ["up", "dn"]:
            feats = build_timeline_features(events, asset)
            if feats:
                all_timeline_features.append({"slug": slug, "asset": asset,
                                              "features": feats})

        n_processed += 1
        if n_processed % 50 == 0:
            print(f"  Processed {n_processed} windows, "
                  f"{len(all_fills):,} fills classified...")

    print(f"\nProcessed {n_processed} windows with L2 data")
    print(f"Skipped {n_skipped} windows (no L2 or too short)")

    if not all_fills:
        print("No fills could be classified. Check L2 data availability.")
        return

    # Generate plots
    plot_07_maker_taker(all_fills)
    plot_08_book_depth(all_fills)
    plot_09_ladder(all_fills)
    plot_10_spread_depth(all_timeline_features)
    plot_11_aggression_triggers(all_fills)
    plot_12_imbalance_signal(all_fills)

    # Summary
    print_summary(all_fills, n_processed, n_skipped)

    print(f"All plots saved to: {OUTDIR}/")
    print("Plots generated: 07-12 (L2-backed analysis)")


if __name__ == "__main__":
    main()
