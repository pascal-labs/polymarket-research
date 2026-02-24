#!/usr/bin/env python3
"""
Reverse-Engineer Market Maker Strategy from BTC 15-Minute Binary Markets

Compares a target wallet's execution prices against market prices at those
exact timestamps to reconstruct their strategy through:

1. Execution quality analysis — are fills better/worse than market mid?
2. Window sequence analysis — running UP/DOWN positions, combined cost
3. Entry pattern detection — timing, side preference, DCA intervals
4. Balance & timing deep dive — how positions evolve through the window
5. P&L calculation — window-level outcomes based on final settlement

The key insight: combined average (up_avg + down_avg) < $1.00 means
guaranteed profit regardless of outcome, since winning shares pay $1.

Data requirements:
    - Wallet fill history (JSON from Polymarket data API)
    - Price log (CSV: timestamp, yes_price, no_price per market)

Note: Uses only publicly available on-chain data.
"""

import json
import csv
import os
from datetime import datetime
from collections import defaultdict
from statistics import mean, median, stdev
from typing import Dict, List, Tuple, Optional


def load_trades(filepath: str) -> List[dict]:
    """Load wallet trades from JSON file, filtering to BUY entries."""
    with open(filepath) as f:
        trades = json.load(f)
    return [t for t in trades if t['side'] == 'BUY']


def load_price_log(filepath: str, target_slugs: set) -> Dict[str, List[dict]]:
    """
    Load price_log.csv into dict keyed by market slug.
    Only load rows for target slugs to save memory.
    """
    from datetime import timezone

    price_data = defaultdict(list)

    with open(filepath) as f:
        reader = csv.DictReader(f)
        for row in reader:
            slug = row['market_id']
            if slug in target_slugs:
                try:
                    ts_str = row['timestamp']
                    if 'T' in ts_str and len(ts_str) > 10:
                        dt = datetime.fromisoformat(ts_str)
                        dt_utc = dt.replace(tzinfo=timezone.utc)
                        ts = dt_utc.timestamp()
                    else:
                        ts = float(ts_str) if ts_str else None
                        if ts is None:
                            continue

                    price_data[slug].append({
                        'timestamp': ts,
                        'yes_price': float(row['yes_price']) if row['yes_price'] else None,
                        'no_price': float(row['no_price']) if row['no_price'] else None,
                        'spread': float(row['spread']) if row['spread'] else 0,
                    })
                except (ValueError, TypeError):
                    continue

    for slug in price_data:
        price_data[slug].sort(key=lambda x: x['timestamp'])

    return price_data


def find_nearest_price(price_data: List[dict], target_ts: float,
                       max_diff: float = 10.0) -> Optional[dict]:
    """Binary search for closest price observation within max_diff seconds."""
    if not price_data:
        return None

    left, right = 0, len(price_data) - 1
    best = None
    best_diff = float('inf')

    while left <= right:
        mid = (left + right) // 2
        diff = abs(price_data[mid]['timestamp'] - target_ts)

        if diff < best_diff:
            best_diff = diff
            best = price_data[mid]

        if price_data[mid]['timestamp'] < target_ts:
            left = mid + 1
        else:
            right = mid - 1

    for i in [left, right, left + 1, right - 1]:
        if 0 <= i < len(price_data):
            diff = abs(price_data[i]['timestamp'] - target_ts)
            if diff < best_diff:
                best_diff = diff
                best = price_data[i]

    if best_diff <= max_diff:
        return best
    return None


def analyze_execution_quality(trades: List[dict],
                              price_data: Dict[str, List[dict]]) -> dict:
    """Compare execution prices to market prices at trade time."""
    results = {
        'up_diffs': [], 'down_diffs': [],
        'matches': 0, 'no_match': 0,
        'better_than_market': 0, 'worse_than_market': 0, 'equal_to_market': 0,
    }

    for trade in trades:
        slug = trade['slug']
        ts = trade['timestamp']
        his_price = trade['price']
        outcome = trade['outcome']

        if slug not in price_data:
            results['no_match'] += 1
            continue

        market = find_nearest_price(price_data[slug], ts)
        if not market:
            results['no_match'] += 1
            continue

        results['matches'] += 1

        if outcome == 'Up':
            market_price = market['yes_price']
            if market_price:
                results['up_diffs'].append(his_price - market_price)
        else:
            market_price = market['no_price']
            if market_price:
                results['down_diffs'].append(his_price - market_price)

        if market_price:
            if his_price < market_price:
                results['better_than_market'] += 1
            elif his_price > market_price:
                results['worse_than_market'] += 1
            else:
                results['equal_to_market'] += 1

    return results


def analyze_window_sequence(trades: List[dict],
                            price_data: Dict[str, List[dict]]) -> List[dict]:
    """Analyze trade sequence within each window — position trajectory."""
    by_slug = defaultdict(list)
    for t in trades:
        by_slug[t['slug']].append(t)

    window_analyses = []

    for slug, window_trades in by_slug.items():
        if slug not in price_data:
            continue

        window_trades.sort(key=lambda x: x['timestamp'])

        try:
            window_start = int(slug.split('-')[-1])
        except Exception:
            continue

        up_shares = up_cost = down_shares = down_cost = 0
        trade_sequence = []
        first_side = None

        for i, trade in enumerate(window_trades):
            secs_into_window = trade['timestamp'] - window_start
            market = find_nearest_price(price_data[slug], trade['timestamp'])
            market_up = market['yes_price'] if market else None
            market_down = market['no_price'] if market else None

            if trade['outcome'] == 'Up':
                up_shares += trade['size']
                up_cost += trade['usdcSize']
                if first_side is None:
                    first_side = 'Up'
            else:
                down_shares += trade['size']
                down_cost += trade['usdcSize']
                if first_side is None:
                    first_side = 'Down'

            up_avg = up_cost / up_shares if up_shares > 0 else 0
            down_avg = down_cost / down_shares if down_shares > 0 else 0
            combined = up_avg + down_avg if up_shares > 0 and down_shares > 0 else None

            total_shares = up_shares + down_shares
            balance_ratio = up_shares / total_shares if total_shares > 0 else 0

            trade_info = {
                'trade_num': i + 1,
                'secs_into_window': secs_into_window,
                'side': trade['outcome'],
                'price': trade['price'],
                'shares': trade['size'],
                'usdc': trade['usdcSize'],
                'market_up': market_up,
                'market_down': market_down,
                'running_up_shares': up_shares,
                'running_down_shares': down_shares,
                'running_up_avg': up_avg,
                'running_down_avg': down_avg,
                'running_combined': combined,
                'balance_ratio': balance_ratio,
            }

            if market_up and market_down:
                trade_info['bought_cheaper'] = (
                    (trade['outcome'] == 'Up' and market_up < market_down) or
                    (trade['outcome'] == 'Down' and market_down < market_up)
                )
                trade_info['market_spread'] = market_up + market_down - 1.0

            trade_sequence.append(trade_info)

        final_up_avg = up_cost / up_shares if up_shares > 0 else 0
        final_down_avg = down_cost / down_shares if down_shares > 0 else 0

        window_analyses.append({
            'slug': slug,
            'window_start': window_start,
            'num_trades': len(window_trades),
            'first_side': first_side,
            'first_trade_secs': trade_sequence[0]['secs_into_window'] if trade_sequence else None,
            'final_up_shares': up_shares,
            'final_down_shares': down_shares,
            'final_up_avg': final_up_avg,
            'final_down_avg': final_down_avg,
            'final_combined': final_up_avg + final_down_avg,
            'total_cost': up_cost + down_cost,
            'balance_ratio': up_shares / (up_shares + down_shares) if (up_shares + down_shares) > 0 else 0,
            'trade_sequence': trade_sequence,
        })

    return window_analyses


def analyze_entry_patterns(window_analyses: List[dict]) -> dict:
    """Analyze entry timing, side selection, and DCA intervals."""
    first_trade_times = []
    first_sides = {'Up': 0, 'Down': 0}
    entries_per_window = []
    bought_cheaper_count = bought_more_expensive_count = 0
    all_intervals = []

    for wa in window_analyses:
        if wa['first_trade_secs'] is not None:
            first_trade_times.append(wa['first_trade_secs'])
        if wa['first_side']:
            first_sides[wa['first_side']] += 1
        entries_per_window.append(wa['num_trades'])

        seq = wa['trade_sequence']
        prev_secs = None
        for t in seq:
            if 'bought_cheaper' in t:
                if t['bought_cheaper']:
                    bought_cheaper_count += 1
                else:
                    bought_more_expensive_count += 1
            if prev_secs is not None:
                all_intervals.append(t['secs_into_window'] - prev_secs)
            prev_secs = t['secs_into_window']

    nonzero_intervals = [i for i in all_intervals if i > 0]

    return {
        'first_trade_median_secs': median(first_trade_times) if first_trade_times else None,
        'first_trade_mean_secs': mean(first_trade_times) if first_trade_times else None,
        'first_side_up_pct': first_sides['Up'] / sum(first_sides.values()) * 100 if sum(first_sides.values()) > 0 else 0,
        'first_side_down_pct': first_sides['Down'] / sum(first_sides.values()) * 100 if sum(first_sides.values()) > 0 else 0,
        'mean_entries_per_window': mean(entries_per_window) if entries_per_window else 0,
        'median_entries_per_window': median(entries_per_window) if entries_per_window else 0,
        'bought_cheaper_count': bought_cheaper_count,
        'bought_more_expensive_count': bought_more_expensive_count,
        'bought_cheaper_pct': bought_cheaper_count / (bought_cheaper_count + bought_more_expensive_count) * 100 if (bought_cheaper_count + bought_more_expensive_count) > 0 else 0,
        'mean_interval_secs': mean(nonzero_intervals) if nonzero_intervals else None,
        'median_interval_secs': median(nonzero_intervals) if nonzero_intervals else None,
        'total_intervals': len(all_intervals),
        'nonzero_intervals': len(nonzero_intervals),
    }


def analyze_combined_achievement(window_analyses: List[dict]) -> dict:
    """Analyze combined average cost across windows."""
    combineds = [wa['final_combined'] for wa in window_analyses if wa['final_combined']]

    under_1 = sum(1 for c in combineds if c < 1.0)
    under_095 = sum(1 for c in combineds if c < 0.95)
    under_090 = sum(1 for c in combineds if c < 0.90)

    return {
        'total_windows': len(combineds),
        'combined_under_1': under_1,
        'combined_under_095': under_095,
        'combined_under_090': under_090,
        'combined_under_1_pct': under_1 / len(combineds) * 100 if combineds else 0,
        'mean_combined': mean(combineds) if combineds else None,
        'median_combined': median(combineds) if combineds else None,
        'best_combined': min(combineds) if combineds else None,
        'worst_combined': max(combineds) if combineds else None,
        'stdev_combined': stdev(combineds) if len(combineds) > 1 else None,
    }


def analyze_balance_and_timing(window_analyses: List[dict]) -> dict:
    """Deep dive into position balance evolution and timing patterns."""
    final_balance_ratios = []
    time_to_sub_dollar = []
    unique_timestamps_per_window = []
    early_balance = []
    mid_balance = []
    late_balance = []
    alternation_counts = []

    for wa in window_analyses:
        seq = wa['trade_sequence']
        if not seq:
            continue

        final_balance_ratios.append(wa['balance_ratio'])
        unique_ts = len(set(t['secs_into_window'] for t in seq))
        unique_timestamps_per_window.append(unique_ts)

        for t in seq:
            if t['running_combined'] and t['running_combined'] < 1.0:
                time_to_sub_dollar.append(t['secs_into_window'])
                break

        n = len(seq)
        if n >= 4:
            early_balance.append(seq[n // 4]['balance_ratio'])
            mid_balance.append(seq[n // 2]['balance_ratio'])
            late_balance.append(seq[3 * n // 4]['balance_ratio'])

        switches = 0
        prev_side = None
        for t in seq:
            if prev_side and t['side'] != prev_side:
                switches += 1
            prev_side = t['side']
        alternation_counts.append(switches)

    return {
        'mean_final_balance': mean(final_balance_ratios) if final_balance_ratios else 0.5,
        'median_final_balance': median(final_balance_ratios) if final_balance_ratios else 0.5,
        'mean_unique_timestamps': mean(unique_timestamps_per_window) if unique_timestamps_per_window else 0,
        'median_unique_timestamps': median(unique_timestamps_per_window) if unique_timestamps_per_window else 0,
        'mean_time_to_sub_dollar': mean(time_to_sub_dollar) if time_to_sub_dollar else None,
        'median_time_to_sub_dollar': median(time_to_sub_dollar) if time_to_sub_dollar else None,
        'windows_achieving_sub_dollar': len(time_to_sub_dollar),
        'mean_early_balance': mean(early_balance) if early_balance else None,
        'mean_mid_balance': mean(mid_balance) if mid_balance else None,
        'mean_late_balance': mean(late_balance) if late_balance else None,
        'mean_alternations': mean(alternation_counts) if alternation_counts else 0,
        'median_alternations': median(alternation_counts) if alternation_counts else 0,
    }


def calculate_pnl(window_analyses: List[dict],
                  price_data: Dict[str, List[dict]]) -> List[dict]:
    """
    Calculate P&L per window based on final settlement.

    Outcome determined by final price: yes_price >= 0.95 means Up won.
    """
    pnl_results = []

    for wa in window_analyses:
        slug = wa['slug']
        if slug not in price_data:
            continue

        prices = price_data[slug]
        if not prices:
            continue

        final = prices[-1]
        outcome = None
        if final['yes_price'] is not None and final['yes_price'] >= 0.95:
            outcome = 'Up'
        elif final['no_price'] is not None and final['no_price'] >= 0.95:
            outcome = 'Down'
        else:
            continue

        total_cost = wa['total_cost']
        payout = wa['final_up_shares'] if outcome == 'Up' else wa['final_down_shares']
        pnl = payout - total_cost
        pnl_pct = (pnl / total_cost) * 100 if total_cost > 0 else 0

        pnl_results.append({
            'slug': slug,
            'outcome': outcome,
            'up_shares': wa['final_up_shares'],
            'down_shares': wa['final_down_shares'],
            'total_cost': total_cost,
            'payout': payout,
            'pnl': pnl,
            'pnl_pct': pnl_pct,
            'combined': wa['final_combined'],
        })

    return pnl_results


def print_report(exec_results, window_analyses, entry_patterns,
                 combined_stats, pnl_results, balance_stats=None):
    """Print comprehensive analysis report."""
    print("=" * 80)
    print("REVERSE ENGINEERING MARKET MAKER STRATEGY — BTC 15-MINUTE BINARIES")
    print("=" * 80)

    print(f"\nTotal windows analyzed: {len(window_analyses)}")
    print(f"Total trades matched: {exec_results['matches']}")
    print(f"Trades without price match: {exec_results['no_match']}")

    if pnl_results:
        wins = sum(1 for p in pnl_results if p['pnl'] > 0)
        total = len(pnl_results)
        total_pnl = sum(p['pnl'] for p in pnl_results)
        print(f"\nWindows with known outcomes: {total}")
        print(f"Win rate: {wins}/{total} ({wins / total * 100:.1f}%)")
        print(f"Total P&L: ${total_pnl:.2f}")

    all_diffs = exec_results['up_diffs'] + exec_results['down_diffs']
    if all_diffs:
        avg_diff = mean(all_diffs) * 100
        print(f"\nExecution quality: {avg_diff:.2f} cents vs market mid")

    print(f"\nCombined < $1.00: {combined_stats['combined_under_1']}/{combined_stats['total_windows']} ({combined_stats['combined_under_1_pct']:.1f}%)")
    print(f"Median combined: ${combined_stats['median_combined']:.4f}")

    if balance_stats:
        print(f"\nFinal balance (UP ratio): {balance_stats['median_final_balance']:.3f}")

    if pnl_results:
        sub_dollar = [p for p in pnl_results if p['combined'] and p['combined'] < 1.0]
        above_dollar = [p for p in pnl_results if p['combined'] and p['combined'] >= 1.0]
        if sub_dollar and above_dollar:
            sub_wins = sum(1 for p in sub_dollar if p['pnl'] > 0)
            above_wins = sum(1 for p in above_dollar if p['pnl'] > 0)
            print(f"\nCombined < $1.00: {sub_wins}/{len(sub_dollar)} wins ({sub_wins / len(sub_dollar) * 100:.0f}%)")
            print(f"Combined >= $1.00: {above_wins}/{len(above_dollar)} wins ({above_wins / len(above_dollar) * 100:.0f}%)")


def main():
    trades_file = os.environ.get("TRADES_FILE", "data/trades.json")
    prices_file = os.environ.get("PRICE_LOG", "data/price_log.csv")

    print("Loading trades...")
    trades = load_trades(trades_file)
    print(f"Loaded {len(trades)} BUY trades")

    slugs = set(t['slug'] for t in trades)
    print(f"Across {len(slugs)} windows")

    print("\nLoading price log...")
    price_data = load_price_log(prices_file, slugs)
    print(f"Loaded price data for {len(price_data)} overlapping windows")

    exec_results = analyze_execution_quality(trades, price_data)
    window_analyses = analyze_window_sequence(trades, price_data)
    entry_patterns = analyze_entry_patterns(window_analyses)
    combined_stats = analyze_combined_achievement(window_analyses)
    balance_stats = analyze_balance_and_timing(window_analyses)
    pnl_results = calculate_pnl(window_analyses, price_data)

    print_report(exec_results, window_analyses, entry_patterns,
                 combined_stats, pnl_results, balance_stats)


if __name__ == '__main__':
    main()
