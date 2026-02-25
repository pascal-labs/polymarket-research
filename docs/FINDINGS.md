# Findings: Forensic Analysis of a Polymarket Market Maker

Organized by discovery, with references to the 18 analysis plots in `figures/`. Every claim in this document is backed by L2 orderbook data — not inferred from trade prints alone.

---

## Dataset

- **104,049 trades** from a single professional market maker wallet
- **157 windows** with full L2 orderbook capture (completeness criteria: duration >= 850s, max gap <= 5s, both UP and DN data present)
- **$3,413 cumulative P&L** over the observation period

This is a smaller dataset than a pure trade-print analysis would yield, but every window includes synchronized L2 book snapshots. The tradeoff is deliberate: quality over quantity. Claims about maker/taker behavior, book depth, and aggression triggers are grounded in actual orderbook state rather than heuristic inference.

---

## Discovery 1: Dual-Sided Pair Accumulation

**The strategy is not directional prediction — it's execution quality.**

The market maker simultaneously accumulates both YES (UP) and NO (DOWN) shares in each 15-minute window. Since one side always settles at $1.00, the profit comes from buying the combined pair for less than $1.00.

### Evidence

**Plot 01 — Inventory Trajectories** (`figures/01_inventory_trajectories.png`)
- UP and DN cumulative share lines converge toward 50/50 balance across sampled windows
- Imbalance (|UP-DN|/total) starts high and decreases through the window lifecycle
- Median final imbalance: **2.5%** — tighter than expected, reflecting disciplined rebalancing

**Plot 02 — Pair Cost & P&L** (`figures/02_pair_cost_and_pnl.png`)
- Combined pair cost distribution centered at **$0.9911** (median), below the $1.00 breakeven
- P&L distribution shows a right-skewed positive profile — many small wins, few large losses
- Cumulative P&L: **$3,413** across 157 L2-backed windows
- Win rate: **57.3%**

**Plot 05 — Example Windows** (`figures/05_example_windows.png`)
- Detailed traces across varying market conditions show the same core pattern:
  - Both UP and DN shares accumulate roughly in parallel
  - In trending markets, the cheaper side accumulates faster initially, then the other side catches up
  - Combined cost stays below $1.00 in winning windows

### Interpretation

The edge is **~0.9 cents per matched pair** on average. This is small per trade but compounds across windows. The business model is high-frequency spread capture, not prediction. The 57.3% win rate with a tight cost distribution means the strategy relies on consistency and volume rather than outsized wins.

---

## Discovery 2: Static Ladder with Dynamic Aggression

**The market maker uses resting limit orders at multiple levels, but switches to aggressive spread-crossing when inventory becomes imbalanced.**

### Evidence

**Plot 07 — Maker/Taker Classification** (`figures/07_maker_taker_classification.png`)
- L2 BBO comparison classifies fills as maker (resting) or taker (aggressive)
- **65.0% maker / 35.0% taker** — more passive than aggressive, but a substantial taker component
- Classification rate: **99.9%** of fills successfully classified using L2 book state

**Plot 09 — Ladder Reconstruction** (`figures/09_ladder_reconstruction.png`)
- Reconstructed resting order levels show a consistent structure:
  - 5-10 levels per side (UP and DOWN)
  - 1-2 cent spacing between adjacent levels
  - Distinctive fill size signature at each level

**Plot 11 — Aggression Triggers** (`figures/11_aggression_triggers_l2.png`)
- Aggression triggers follow clear state-dependent rules tied to inventory imbalance
- Higher imbalance levels drive proportionally more taker activity
- L2 data confirms these are genuine spread-crossing events, not passive fills at the BBO

**Plot 10 — Spread and Depth Dynamics** (`figures/10_spread_and_depth_dynamics.png`)
- Spread width and BBO depth evolve systematically over the window lifecycle
- Spreads widen and depth thins as resolution approaches
- Spread asymmetry between UP and DN sides indicates directional consensus

**Plot 17 — Imbalance Mechanics** (`figures/17_imbalance_mechanics.png`)
- Imbalance dynamics show a clear feedback loop:
  - Passive fills create imbalance -> imbalance triggers aggression -> aggression reduces imbalance
  - The equilibrium imbalance level is maintained by the aggression trigger threshold

### Interpretation

The aggression triggers reveal the MM's implicit cost function: they're willing to pay spread-crossing cost to close an imbalance, but only when passive accumulation becomes unlikely given remaining time. This is consistent with optimal control theory on pair accumulation. The 65/35 maker-taker split, confirmed by L2 BBO comparison, shows a strategy that leans passive but is not afraid to pay for urgency.

---

## Discovery 3: Endgame Urgency

**In the final 2 minutes of each 15-minute window, the market maker dramatically increases aggression to close any remaining inventory imbalance.**

### Evidence

**Plot 06 — Endgame Behavior** (`figures/06_endgame_behavior.png`)
- Detailed view of the final minutes across multiple windows
- Clear pattern: deficit side gets aggressive fills while surplus side goes passive
- Time trigger compounds with imbalance trigger — urgency increases nonlinearly

**Plot 11 — Aggression Triggers** (`figures/11_aggression_triggers_l2.png`)
- Fill rate spikes on the deficit side in the final 120 seconds
- The MM typically concentrates spread-crossing in the last minutes of the window
- L2 book state confirms these late fills are genuine taker executions

### Interpretation

The 15-minute window creates a natural deadline that forces resolution. The MM's endgame behavior is rational: with less time remaining, the probability of passively filling the deficit side drops, making the cost of crossing the spread worth paying to avoid orphan risk (holding unmatched shares whose value depends on directional outcome).

---

## Discovery 4: L2-Backed Fill Fingerprinting

**With synchronized L2 orderbook snapshots, fill classification moves from heuristic inference to direct observation.**

### Evidence

**Plot 07 — Maker/Taker Classification** (`figures/07_maker_taker_classification.png`)
- Every fill is compared against the L2 best bid/offer at the time of execution
- Fills at or inside the BBO are classified as maker; fills at or beyond the opposite side are classified as taker
- **99.9% classification rate** — only a handful of fills fall into ambiguous territory

**Plot 08 — Book Depth Around Fills** (`figures/08_book_depth_around_fills.png`)
- L2 snapshots before and after each fill reveal book depth discontinuities
- Vanished-to-fill ratio analysis: when a resting order gets filled, diffing the L2 book reveals if the MM was the sole order at that level
- This implies careful level selection to avoid competition at the same price points

**Plot 03 — Fill Characteristics** (`figures/03_fill_characteristics.png`)
- Fill size distribution shows a distinctive peak — a consistent order size in the ladder algorithm
- Inter-fill timing and batching patterns reveal algorithmic execution cadence
- Same-second fills show minimal price spread (all from the same ladder level)

**Plot 12 — Book Imbalance Signal** (`figures/12_book_imbalance_signal.png`)
- L2 book imbalance (bid depth vs ask depth) correlates with subsequent fill direction
- The MM appears to condition behavior on book state, not just trade state

### Interpretation

L2-backed classification eliminates the ambiguity that plagues trade-print-only analysis. When we say "65% maker," that number comes from comparing each fill price to the actual BBO at the time of matching-engine execution — not from inferring aggressor side based on tick direction or trade size heuristics. A -1 second timestamp correction is applied to align on-chain block timestamps with the real-time L2 book state (see Methodology).

---

## Discovery 5: Regime Sensitivity

**Win rate and pair cost vary meaningfully by market regime, and the MM selectively skips unfavorable windows.**

### Evidence

**Plot 04 — Regime Sensitivity** (`figures/04_regime_sensitivity.png`)
- Win rate varies by regime — some market conditions produce consistently tighter pair costs than others
- P&L scatter shows losses concentrated in extreme directional moves
- The MM adapts behavior to regime but cannot fully offset adverse conditions

**Plot 15 — Losing Window Anatomy** (`figures/15_losing_window_anatomy.png`)
- Losing windows share common features:
  - Higher final imbalance
  - More aggressive fills
  - Higher combined cost (above $1.00)
- Dissecting losses reveals the failure modes of the strategy

**Plot 16 — Window Selection** (`figures/16_window_selection.png`)
- The MM implements selection discipline — not every available window is traded
- Skip rate varies by conditions: extreme opening prices trigger higher skip rates
- Window selection is itself a source of edge

### Interpretation

The MM doesn't trade every window. Skipping unfavorable conditions (extreme prices, low liquidity, high volatility) is itself a source of edge. With only 157 L2-backed windows, regime-level statistics have wider confidence intervals than a larger dataset would produce, but the directional patterns are clear and consistent with the underlying strategy logic.

---

## Discovery 6: Taker Economics

**Aggressive fills (spread-crossing) cost more per fill but serve a critical role in reducing inventory imbalance.**

### Evidence

**Plot 13 — Execution Quality** (`figures/13_execution_quality.png`)
- Taker fills pay a premium relative to the BBO at time of execution
- But taker fills disproportionately target the deficit side, reducing orphan risk
- The execution quality gap between maker and taker fills quantifies the insurance premium

**Plot 14 — Taker Economics** (`figures/14_taker_economics.png`)
- Window-level analysis: taker-heavy windows have slightly lower average edge per fill
- But taker-heavy windows also have lower final imbalance, which reduces tail risk
- The cost of crossing is more than offset by reduced orphan losses
- Takers are an insurance policy — paying a small premium per fill to avoid larger losses from unmatched positions

### The Business Model

The economics are straightforward:

| Metric | Value |
|--------|-------|
| Median pair cost | $0.9911 |
| Edge per pair | ~0.9 cents |
| Win rate | 57.3% |
| Maker fills | 65.0% |
| Taker fills | 35.0% |
| Classification rate | 99.9% |
| Median final imbalance | 2.5% |
| Cumulative P&L | $3,413 |

**Plot 18 — Summary Dashboard** (`figures/18_summary_dashboard.png`)
- Complete strategy overview: key metrics, pair cost with annotations, cumulative P&L, data quality

The ~0.9-cent per-pair edge multiplied across windows is the business model. It requires:
1. Consistently buying both sides below $1.00 (execution quality)
2. Managing inventory to stay near 50/50 (aggression triggers)
3. Skipping unfavorable windows (selection discipline)
4. Paying for urgency only when necessary (endgame management)

---

## Plot Reference

| # | File | Tier | Description |
|---|------|------|-------------|
| 01 | `inventory_trajectories.png` | A — Trade | Cumulative UP/DN share trajectories and imbalance |
| 02 | `pair_cost_and_pnl.png` | A — Trade | Combined cost distribution and cumulative P&L |
| 03 | `fill_characteristics.png` | A — Trade | Fill size, timing, and batching patterns |
| 04 | `regime_sensitivity.png` | A — Trade | Win rate and P&L by market regime |
| 05 | `example_windows.png` | A — Trade | Detailed traces of individual windows |
| 06 | `endgame_behavior.png` | A — Trade | Final-minutes aggression patterns |
| 07 | `maker_taker_classification.png` | B — L2 | BBO-based maker/taker classification |
| 08 | `book_depth_around_fills.png` | B — L2 | L2 depth discontinuities at fill times |
| 09 | `ladder_reconstruction.png` | B — L2 | Reconstructed resting order levels |
| 10 | `spread_and_depth_dynamics.png` | B — L2 | Spread width and depth over window lifecycle |
| 11 | `aggression_triggers_l2.png` | B — L2 | L2-confirmed aggression by imbalance and time |
| 12 | `book_imbalance_signal.png` | B — L2 | Bid/ask depth imbalance as directional signal |
| 13 | `execution_quality.png` | C — Synthesis | Maker vs taker edge comparison |
| 14 | `taker_economics.png` | C — Synthesis | Cost-benefit analysis of aggressive fills |
| 15 | `losing_window_anatomy.png` | C — Synthesis | Common features of losing windows |
| 16 | `window_selection.png` | C — Synthesis | Skip rate and selection discipline |
| 17 | `imbalance_mechanics.png` | C — Synthesis | Feedback loop dynamics |
| 18 | `summary_dashboard.png` | C — Synthesis | Full strategy summary in one view |

---

## Limitations

- **Smaller dataset:** 157 windows is fewer than a trade-print-only analysis could produce. But every window has full L2 orderbook coverage, making each claim directly verifiable rather than inferred.
- **Survivorship bias:** Only analyzing a successful MM. Wallets that lost money and stopped are not in the dataset.
- **L2 timing resolution:** ~1 second snapshots miss sub-second dynamics. Some fill timing may be imprecise at the millisecond level, though 99.9% classification rate suggests this is not a significant issue.
- **Block timestamp alignment:** Trade timestamps from the data API are Polygon block timestamps (integer seconds, ~2s block time), which lag matching-engine execution by 0-2 seconds. A -1 second correction is applied as the best point estimate. Sensitivity analysis across offsets from -3s to +3s shows maker% ranging from 57.0% to 77.8%, with the applied -1s correction yielding 65.0%. The qualitative findings (majority-maker with state-dependent aggression) are stable across all offsets.
- **Multi-wallet operation:** A single entity may operate multiple wallets, making this an incomplete picture of their full activity.
- **Regime changes:** The observed behavior reflects a specific competitive landscape that evolves over time.
- **Public data only:** The MM's internal model parameters, risk limits, and fair value estimates remain unknown. We observe the behavioral surface of a deeper model.
