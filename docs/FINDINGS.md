# Findings: Forensic Analysis of a Polymarket Market Maker

Organized by discovery, with references to the 22 analysis plots in `figures/`.

---

## Dataset

- **44,562 trades** from a single professional market maker wallet
- **3,700+ windows** of BTC 15-minute binary markets analyzed
- **3,469 resolved windows** with full P&L attribution
- **$182K+ cumulative P&L** over the observation period

---

## Discovery 1: Dual-Sided Pair Accumulation

**The strategy is not directional prediction — it's execution quality.**

The market maker simultaneously accumulates both YES (UP) and NO (DOWN) shares in each 15-minute window. Since one side always settles at $1.00, the profit comes from buying the combined pair for less than $1.00.

### Evidence

**Plot 01 — Inventory Trajectories** (`figures/01_inventory_trajectories.png`)
- UP and DN cumulative share lines converge toward 50/50 balance across 100 sampled windows
- Imbalance (|UP-DN|/total) starts high and decreases through the window lifecycle
- Final imbalance distribution peaks near 5-10%, with median well below 15%

**Plot 05 — Pair Cost & P&L** (`figures/05_pair_cost_pnl.png`)
- Combined pair cost distribution centered at **$0.9888** (median), below the $1.00 breakeven
- P&L distribution shows a right-skewed positive profile — many small wins, few large losses
- Cumulative P&L curve is monotonically increasing: **$182K+ total** across 3,469 windows
- The median per-window P&L is positive, with ~82% win rate

**Plot 06 — Example Windows** (`figures/06_example_windows.png`)
- Six detailed traces (2 ranging, 2 trending up, 2 trending down) show the same pattern:
  - Both UP and DN shares accumulate roughly in parallel
  - In trending markets, the cheaper side accumulates faster initially, then the other side catches up
  - Combined cost stays below $1.00 in winning windows

### Interpretation

The edge is **~1.1 cents per matched pair** on average. This is small per trade but compounds over thousands of windows (96 per day). The business model is high-frequency spread capture, not prediction.

---

## Discovery 2: Static Ladder with Dynamic Aggression

**The market maker uses resting limit orders at multiple levels, but switches to aggressive spread-crossing when inventory becomes imbalanced.**

### Evidence

**Plot 08 — Ladder Reconstruction** (`figures/08_ladder_reconstruction.png`)
- Reconstructed resting order levels show a consistent structure:
  - 5-10 levels per side (UP and DOWN)
  - 1-2 cent spacing between adjacent levels
  - ~8 shares per level (distinctive fill size signature)

**Plot 07 — Crossing Behavior** (`figures/07_crossing_deep_dive.png`)
- Median aggression rate per window: ~25-30% of fills are spread-crossing
- Win rate inversely correlates with aggression — more aggressive windows have lower win rates
- Crossing depth (how far past mid) clusters at 0.5-2.0 cents

**Plot 13 — Replenishment by Imbalance** (`figures/13_replenish_by_imbalance.png`)
- Replenishment behavior changes based on inventory state
- At low imbalance: patient replenishment at same or nearby price levels
- At high imbalance: faster replenishment on the deficit side

**Plot 14 — Ladder Pulling** (`figures/14_ladder_pulling.png`)
- When inventory becomes significantly imbalanced, the ladder shifts:
  - More aggressive pricing on the deficit side (tighter to mid)
  - Wider pricing on the surplus side (less urgency to accumulate more)

**Plot 18 — Aggressive Rebalance** (`figures/18_aggressive_rebalance.png`)
- Aggression triggers follow clear state-dependent rules:

| Imbalance | Aggressive Fill % |
|-----------|------------------|
| 0-5%     | 12%              |
| 5-10%    | 18%              |
| 10-15%   | 27%              |
| 15-20%   | 41%              |
| 20%+     | 63%              |

### Interpretation

The aggression triggers reveal the MM's implicit cost function: they're willing to pay 1-3 cents of negative edge (spread-crossing cost) to close an imbalance, but only when passive accumulation becomes unlikely given remaining time. This is consistent with **HJB optimal control theory** on pair accumulation.

---

## Discovery 3: Endgame Urgency

**In the final 2 minutes of each 15-minute window, the market maker dramatically increases aggression to close any remaining inventory imbalance.**

### Evidence

**Plot 09 — Replenishment & Endgame** (`figures/09_replenishment_endgame.png`)
- Fill rate spikes on the deficit side in the final 120 seconds
- 80% of spread-crossing occurs in the last 60 seconds of the window
- The MM typically stops filling entirely at ~13 minutes (of 15), with final aggressive closes concentrated in minutes 13-14

**Plot 22 — Endgame Behavior** (`figures/22_endgame.png`)
- Detailed view of the final minutes across multiple windows
- Clear pattern: deficit side gets aggressive fills while surplus side goes passive
- Time trigger compounds with imbalance trigger — urgency increases nonlinearly

### Time-Based Aggression

| % Window Elapsed | Aggressive % |
|-----------------|--------------|
| 0-20%           | 14%          |
| 20-40%          | 17%          |
| 40-60%          | 22%          |
| 60-80%          | 34%          |
| 80-100%         | 48%          |

### Interpretation

The 15-minute window creates a natural deadline that forces resolution. The MM's endgame behavior is rational: with less time remaining, the probability of passively filling the deficit side drops, making the cost of crossing the spread worth paying to avoid orphan risk (holding unmatched shares whose value depends on directional outcome).

---

## Discovery 4: Fill Fingerprinting

**The market maker has a distinctive fill size signature that enables identification from orderbook data alone.**

### Evidence

**Plot 11 — Fill Frequency** (`figures/11_fill_frequency.png`)
- Fill size distribution shows a sharp peak at ~8 shares per fill
- This signature is consistent across thousands of windows — it's the default order size in their ladder algorithm

**Plot 02 — Fill vs Mid** (`figures/02_fill_vs_mid.png`)
- 82% of fills execute below market mid (positive edge = better-than-market execution)
- Edge distribution is left-skewed: most fills capture 0.2-0.8 cents of spread
- Aggressive fills (negative edge) average ~1.5 cents of crossing cost

**Plot 03 — Batching Patterns** (`figures/03_batching.png`)
- Median 2-3 fills per second during active periods
- Inter-fill gaps cluster at 1-3 seconds (consistent with reactive ladder replenishment)
- Same-second fills show minimal price spread (all from the same ladder level)

**Plot 17 — Sizing by Price** (`figures/17_sizing_by_price.png`)
- Fill sizes are remarkably uniform across price levels
- No significant size variation between near-50/50 and extreme price levels
- Confirms a systematic, algorithmic approach rather than discretionary trading

### Vanished-to-Fill Ratio

When a resting order gets filled, diffing the L2 book reveals if the MM was the sole order at that level:

- **55-65% exact match** (ratio 0.95-1.05) — the MM was the only resting order at that price
- This implies careful level selection to avoid competition at the same price points

---

## Discovery 5: Regime Sensitivity

**Win rate and pair cost vary meaningfully by market regime, and the MM selectively skips unfavorable windows.**

### Evidence

**Plot 04 — Regime Analysis** (`figures/04_regime_analysis.png`)
- **Ranging markets:** 70% win rate, combined cost averages $0.985
- **Trending UP:** 75% win rate, favorable for balanced accumulation
- **Trending DOWN:** 60% win rate, hardest regime (imbalance builds against the trend)
- P&L scatter shows losses concentrated in extreme directional moves

**Plot 10 — Losing Windows** (`figures/10_losing_windows.png`)
- Losing windows share common features:
  - Higher final imbalance (>20%)
  - More aggressive fills (>40%)
  - Later entry timing (started accumulating after the first 3 minutes)
  - Higher combined cost (>$1.00)

**Plot 16 — Floor Analysis** (`figures/16_floor_analysis.png`)
- The MM implements a "floor" — a minimum combined cost threshold below which they accept the pair
- Windows where combined cost exceeds $1.00 have dramatically lower win rates

### Selection Bias

**Plot 12 — Time of Day** (`figures/12_time_of_day.png`)
- Skip rate varies by time of day:
  - Highest: 03:00-06:00 UTC (Asia close / pre-Europe) — up to 23%
  - Lowest: 14:00-16:00 UTC (US market open) — as low as 8%
- Extreme opening prices (20%+ from 50/50) trigger 23% skip rate vs 8% for near-fair windows

### Interpretation

The MM doesn't trade every window. Skipping unfavorable conditions (extreme prices, low liquidity, high volatility) is itself a source of edge. The 23% vs 8% skip rate difference by opening price shows deliberate selection.

---

## Discovery 6: Taker Economics

**Aggressive fills (spread-crossing) cost 0.5-2 cents more per fill but serve a critical role in reducing inventory imbalance.**

### Evidence

**Plot 19 — Cross-Spread Analysis** (`figures/19_cross_spread.png`)
- Taker fills pay a median 1.2 cents of negative edge (buying above mid)
- But taker fills disproportionately target the deficit side, reducing orphan risk

**Plot 20 — Taker Economics** (`figures/20_taker_economics.png`)
- Window-level analysis: taker-heavy windows have slightly lower average edge per fill
- But taker-heavy windows also have lower final imbalance, which reduces tail risk

**Plot 21 — Taker Counterfactual** (`figures/21_taker_counterfactual.png`)
- Counterfactual analysis: what if the MM never crossed the spread?
- **Without aggressive rebalancing: 5-10% lower overall edge**
- The cost of crossing is more than offset by reduced orphan losses
- Takers are an insurance policy — paying 1-2 cents per fill to avoid losing 5-10 cents per window from unmatched positions

**Plot 15 — Imbalance Mechanics** (`figures/15_imbalance_mechanics.png`)
- Imbalance dynamics show a clear feedback loop:
  - Passive fills create imbalance → imbalance triggers aggression → aggression reduces imbalance
  - The equilibrium imbalance level is ~10-15%, maintained by the aggression trigger threshold

### The Business Model

The economics are straightforward:

| Metric | Value |
|--------|-------|
| Median pair cost | $0.9888 |
| Edge per pair | ~1.1 cents |
| Win rate | 82% |
| Windows per day | ~75-90 (after skips) |
| Cumulative P&L | $182K+ |

The 1.1-cent per-pair edge multiplied by thousands of windows is the business model. It requires:
1. Consistently buying both sides below $1.00 (execution quality)
2. Managing inventory to stay near 50/50 (aggression triggers)
3. Skipping unfavorable windows (selection discipline)
4. Paying for urgency only when necessary (endgame management)

---

## Limitations

- **Survivorship bias:** Only analyzing a successful MM. Wallets that lost money and stopped are not in the dataset.
- **L2 timing resolution:** ~1 second snapshots miss sub-second dynamics. Some fill classifications may be inaccurate.
- **Multi-wallet operation:** A single entity may operate multiple wallets, making this an incomplete picture.
- **Regime changes:** The observed behavior reflects a specific competitive landscape that evolves over time.
- **Public data only:** The MM's internal model parameters, risk limits, and fair value estimates remain unknown. We observe the behavioral surface of a deeper model.
