# Market Maker Analysis: Findings

Detailed write-up of discoveries from analyzing the behavior of Polymarket's most active algorithmic market makers on BTC 15-minute binary markets.

## Background

Polymarket's BTC Up/Down 15-minute markets create a new binary contract every 15 minutes: "Will BTC be higher or lower than the opening price at market close?" These markets trade continuously for ~15 minutes, with YES/NO shares that settle at $1/$0. The rapid turnover (96 markets per day) creates a high-frequency environment where algorithmic market makers dominate.

The key structural feature: **Polymarket runs on Polygon**, meaning every trade is attributed to a specific wallet address. Unlike traditional exchanges where order flow is anonymized, we can reconstruct the complete trading history of any participant.

## Methodology

### Data Collection
- **Fill history**: ~3.2M trades from target wallets, fetched via Polymarket Subgraph API
- **L2 orderbook**: WebSocket-captured book snapshots at ~1 second intervals (JSONL.gz)
- **Price log**: Continuous YES/NO price feed (~1Hz) for market state reconstruction
- **Time period**: Multiple months of 15-minute BTC markets

### Analysis Pipeline

1. **Fill Classification**: For each fill, diff L2 book snapshots before/after to determine if the wallet was maker (passive, resting order filled) or taker (aggressive, crossed spread)

2. **Feature Extraction**: Match each fill against price data to compute edge, market state (spread, skew, momentum, volatility), and position state (inventory balance, imbalance)

3. **Behavioral Analysis**: Segment fills by market conditions to identify decision boundaries

---

## Finding 1: Static Ladder Strategy with Dynamic Aggression

The dominant market makers use a **static ladder strategy** — resting limit orders at multiple price levels on both YES and NO sides. This is structurally similar to the academic "optimal market making in binary markets" literature, but with important practical modifications.

### Ladder Structure

From L2 fingerprinting:
- **Level count**: 5-10 levels per side (UP and DOWN)
- **Level spacing**: 1-3 cents between adjacent levels
- **Order sizes**: 150-300 shares per level (varies by imbalance)
- **Price range**: Typically spanning 0.40-0.60 for YES, corresponding complement for NO

The ladder is **symmetric around fair value** in balanced conditions, but shifts when inventory becomes imbalanced.

### Aggression Triggers

The most revealing finding: market makers switch from passive (maker) to aggressive (taker) fills based on specific state variables.

**Key trigger: Position imbalance**
When the ratio of UP shares to DOWN shares exceeds ~60:40, the market maker begins crossing the spread on the deficit side. This is inventory risk management — they're willing to pay the spread to reduce directional exposure.

```
Imbalance    Aggressive Fill %
  0-5%            12%
  5-10%           18%
  10-15%          27%
  15-20%          41%
  20%+            63%
```

**Secondary trigger: Time remaining**
Aggression increases sharply in the final 30% of the window. With less time for mean reversion, the cost of holding imbalanced inventory rises.

```
% Window Elapsed    Aggressive %
  0-20%                 14%
  20-40%                17%
  40-60%                22%
  60-80%                34%
  80-100%               48%
```

**Interaction effect**: The imbalance and time triggers compound. A 15% imbalance at 80% elapsed triggers aggressive fills at 3x the base rate.

### Interpretation

This behavior is consistent with **optimal pair accumulation** from the academic literature — the market maker wants to accumulate matched YES+NO pairs (which pay $1 guaranteed) while minimizing orphan risk (holding unmatched shares that depend on outcome direction).

The aggression triggers reveal the market maker's **implicit cost function**: they're willing to pay up to 2-3 cents of negative edge to close an imbalance, but only when time pressure makes passive accumulation unlikely.

---

## Finding 2: Selection Bias as a Signal

Not all windows are traded equally. Analysis of skip patterns reveals:

### Skip Rate by Conditions

```
Opening distance from 50/50    Skip Rate
  0-5% (near 50/50)              8%
  5-10%                          11%
  10-20%                         14%
  20%+ (extreme)                 23%
```

Market makers trade *less frequently* when the opening price is extreme (far from 50/50). This makes sense: in a market already pricing at 80% YES, the spread is wider, liquidity is thinner, and the binary outcome is less uncertain.

### Skip Streaks and Capital Rotation

Skip patterns show two distinct modes:
1. **Single-window skips** (~65% of skips): Selective — conditions didn't meet threshold
2. **Multi-window skips** (~35% of skips): Capital rotation — waiting for redemption of winning shares from previous windows

The multi-window streaks (2-4 consecutive skips) are consistent with **capital locked in pending redemption**. Polymarket share redemption requires on-chain transactions that take time to process.

### Hour-of-Day Effects

Skip rates are highest during:
- 03:00-06:00 UTC (Asia close / pre-Europe)
- 10:00-12:00 UTC (mid-morning lull)

And lowest during:
- 14:00-16:00 UTC (US market open overlap)
- 20:00-22:00 UTC (US evening, highest retail activity)

This mirrors traditional market making patterns — provide liquidity when flow is highest, withdraw when adverse selection risk increases relative to flow.

---

## Finding 3: Fill Size Fingerprinting

The most actionable output: market makers have **distinctive order size signatures** that allow identification even without knowing the wallet.

### Common Size Patterns
- **Wallet A**: Heavy clustering at 200-share fills (42% of all fills), with 100-share fills at edges
- **Wallet B**: More uniform distribution, 150-250 range, suggesting dynamic sizing
- **Wallet C**: Round-lot preference (100, 200, 300), likely simpler ladder algorithm

### Vanished-to-Fill Ratio
When a market maker's order gets filled, the vanished quantity at that price level tells us if they were the **sole order** or one of many:
- Ratio ~1.0: They were the only resting order at that price (common at off-center levels)
- Ratio >1.5: Other orders at the same price (common at round-number prices like 0.50)

**55-65% of maker fills show exact match** (ratio 0.95-1.05), meaning the market maker is frequently the only resting order at their price levels. This implies the ladder levels are carefully chosen to avoid overlap with other participants.

---

## Finding 4: Winning vs. Losing Windows

Aggregating to window-level outcomes reveals structural differences:

| Metric | Winning Windows | Losing Windows | Delta |
|--------|----------------|----------------|-------|
| Fill count | Higher | Lower | +15-20% |
| Aggressive % | Lower | Higher | -8pp |
| Entry timing | Earlier | Later | -5% of window |
| Final balance | Near 50% | Skewed | -12pp imbalance |
| Combined cost | Lower | Higher | -1.2 cents |

**Key insight**: Winning windows have MORE fills (better execution), LESS aggression (more patience), and MORE balanced inventory. This is consistent with the theoretical prediction that **forced aggression destroys edge** — when a market maker has to cross the spread to manage risk, they're paying for urgency.

### Combined Cost Analysis
The single most predictive metric: **average combined cost per pair** (YES_avg_price + NO_avg_price for matched shares).
- Winning: combined cost averaging ~$0.97-0.98 (2-3 cent profit per pair)
- Losing: combined cost averaging ~$0.99-1.00 (breakeven to negative per pair)
- The entire edge is captured in the **pair spread** — buying both sides below $1.

---

## Finding 5: Replenishment Dynamics

After a fill, how quickly does the market maker replenish their ladder?

### Inter-Fill Timing
- **Median inter-fill gap**: 1.5-3.0 seconds
- **Mean gap**: 4-8 seconds (skewed by pauses)
- **Minimum gap**: 0.3-0.5 seconds (latency floor)

### Replenishment Pattern
After a fill sweeps one of their levels:
- **50% of the time**: New order appears at the same price within 2 seconds
- **30% of the time**: New order appears at a *different* price (ladder adjustment)
- **20% of the time**: No replenishment (level abandoned, usually near window end)

This suggests a **reactive ladder** — the structure is mostly static, but the market maker adjusts level placement after fills based on updated inventory state.

---

## Implications for Strategy Design

### What This Research Reveals

1. **The edge appears to be in the pair spread**: Based on our analysis, successful market making on Polymarket's binary markets comes from accumulating YES+NO pairs below $1.00, not from directional prediction. The observed 2-3 cent spread per pair is the structural edge for the wallets we studied.

2. **Aggression is costly**: Every aggressive fill costs 1-3 cents of edge. Strategy design should minimize forced crossing — this means better inventory management and more patient accumulation.

3. **Selection matters**: The best market makers *don't trade every window*. Skipping unfavorable conditions (extreme prices, low liquidity, high vol) preserves edge.

4. **Time creates urgency**: The 15-minute window creates a natural deadline that forces resolution of imbalanced positions. Strategies that handle end-of-window dynamics better capture more edge.

### What This Research Does NOT Reveal

This analysis shows *how* the dominant market makers behave, not *why* in terms of their specific model parameters. Their fair value estimates, risk limits, and exact ladder algorithms remain private. The public behavior is the observable surface of a deeper model.

---

## Limitations

- **Survivorship bias**: We only analyzed successful market makers (high volume implies survival). Wallets that lost money and stopped trading are not in the dataset.
- **L2 timing resolution**: Book snapshots at ~1 second intervals miss sub-second dynamics. Some fills may be misclassified.
- **Multi-wallet operation**: A single entity may operate multiple wallets, making wallet-level analysis incomplete.
- **Regime changes**: Market maker behavior may shift as competition increases or as Polymarket's market structure evolves.
