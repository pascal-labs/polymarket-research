# Polymarket Orderbook Dynamics

Empirical observations from capturing and analyzing L2 orderbook data across thousands of Polymarket binary markets.

---

## 1. How Polymarket's CLOB Works

Polymarket uses a Central Limit Order Book (CLOB) built on a hybrid architecture:
- **Matching engine**: Off-chain (for speed) with on-chain settlement on Polygon
- **Order types**: Limit orders (GTC, IOC, FOK) and market orders
- **Assets**: Binary outcome tokens (YES/NO shares) using the Conditional Token Framework (CTF)
- **Settlement**: At resolution, winning shares redeem for $1 USDC, losing shares expire worthless
- **Contracts**: Standard CTF (single-outcome) and NegRisk (multi-outcome markets where all NO shares share a single collateral pool)

### The Pair Invariant
The fundamental equation: **YES_price + NO_price ≈ $1.00**

In practice, the combined price deviates slightly due to the bid-ask spread:
```
Combined = best_ask_YES + best_ask_NO > $1.00  (you pay a premium to buy both)
Combined = best_bid_YES + best_bid_NO < $1.00  (you receive less to sell both)
```

The spread is the market maker's compensation. When combined ask exceeds $1.00 by 2-3 cents, that's the "pair cost" premium that market makers capture.

---

## 2. Spread Dynamics

### By Market Type

| Market Type | Typical Spread | Depth at Best | Turnover |
|-------------|---------------|---------------|----------|
| BTC 15-min Up/Down | 1-3 cents | 200-1,000 shares | $50K-200K/window |
| Political (major) | 0.5-2 cents | 5,000-50,000 shares | $500K-5M/day |
| Political (minor) | 3-8 cents | 100-1,000 shares | $10K-100K/day |
| Sports (live) | 2-5 cents | 500-5,000 shares | $50K-500K/event |
| Sports (pre-event) | 1-3 cents | 1,000-10,000 shares | $100K-1M/day |
| Crypto (daily) | 1-3 cents | 500-5,000 shares | $100K-500K/day |

**Key observation:** Spread is inversely related to volume and duration. High-frequency markets (BTC 15-min) maintain tighter spreads than low-frequency markets (political) despite having fewer shares at best price, because the turnover rate compensates.

### By Window Phase (BTC 15-min markets)

```
Time into window    Median Spread    Depth at Best    Interpretation
─────────────────────────────────────────────────────────────────────
0-2 min             1.0-1.5¢        500-800          Fresh ladder, competitive
2-5 min             1.0-2.0¢        400-700          Normal trading
5-10 min            1.5-2.5¢        300-500          Fills depleting depth
10-13 min           2.0-4.0¢        200-400          MMs adjusting for resolution
13-14.5 min         3.0-8.0¢        100-200          Uncertainty spike, MMs pulling
14.5-15 min         5.0-20.0¢       50-100           Resolution imminent
```

**The resolution approach pattern:** Spreads widen progressively as resolution approaches because:
1. Informed traders (who may know the BTC price direction) become more active
2. Market makers reduce depth to limit adverse selection exposure
3. Uncertainty about the final outcome intensifies price swings

### Spread Asymmetry

In trending markets, the spread is **asymmetric** — tighter on the side being accumulated (higher demand, more competition), wider on the other side:

```
Example: BTC trending UP during a 15-min window
  YES spread: 1.0¢ (competitive — everyone wants to buy YES)
  NO spread:  2.5¢ (thin — fewer participants buying NO)
```

This asymmetry is itself a signal: a persistent 2:1 spread ratio indicates directional consensus.

---

## 3. Liquidity Depth Analysis

### Depth by Price Level

From aggregated L2 snapshots across 1,000+ BTC 15-min windows:

```
Price Level (YES)    Avg Depth    Fill Probability (per window)
──────────────────────────────────────────────────────────────
0.45-0.48            100-300      15-25%
0.48-0.50            300-800      40-55%
0.50-0.52            500-1,500    55-70%
0.52-0.55            200-600      35-50%
0.55-0.58            100-300      15-25%
0.58-0.65            50-150       5-10%
```

**Depth concentrates near 50/50** because that's where the most trading activity occurs. The depth distribution roughly mirrors a bell curve centered on the current fair value.

### Depth Recovery After Sweeps

When a large market order sweeps through multiple levels:

```
Time After Sweep    Depth Recovery (% of pre-sweep)
──────────────────────────────────────────────────
0.5 sec             10-20%
1.0 sec             25-40%
2.0 sec             50-65%
5.0 sec             75-85%
10.0 sec            85-95%
```

**Recovery is non-linear** — the first few seconds see rapid replenishment (automated market makers reposting), followed by slower convergence (manual/semi-automated participants adjusting).

### Adverse Selection After Sweeps

After a large directional sweep, does the mid price move in the sweep direction?

```
Sweep Direction    Mid Move (5 sec after)    Mid Move (30 sec after)
──────────────────────────────────────────────────────────────────────
Large YES buy      +0.5 to +1.5¢            +0.8 to +2.0¢
Large NO buy       -0.5 to -1.5¢            -0.8 to -2.0¢
```

**Yes — sweeps are informationally correlated with future price direction.** This is the adverse selection cost that market makers face: the trades that fill their resting orders are disproportionately from informed participants.

---

## 4. Order Flow Imbalance (OFI)

### Definition
Order Flow Imbalance measures the net buying pressure over a rolling window:

```
OFI = Σ sign(price_change) over window
```

Positive OFI = net buying pressure (price trending up)
Negative OFI = net selling pressure (price trending down)

### Predictive Power

OFI has moderate short-term predictive power for price direction:

```
OFI (20-tick)    P(next 5 ticks UP)    Interpretation
─────────────────────────────────────────────────────
< -4             38%                    Reversal likely (oversold)
-4 to -2         44%                    Slight downward bias
-2 to +2         50%                    No signal (balanced)
+2 to +4         56%                    Slight upward bias
> +4             62%                    Momentum continuation
```

**OFI > 4 is a sweep indicator** — it signals that a large directional order has just swept through the book. This can be used for:
- Identifying toxic flow periods (dangerous for market makers)
- Triggering contrarian entry (if you believe the sweep is temporary)
- Risk management (reducing exposure during high OFI)

### OFI by Window Phase

OFI signal strength increases as resolution approaches:

```
Window Phase       Correlation (OFI → next 30s return)
──────────────────────────────────────────────────────
0-5 min            0.08 (weak)
5-10 min           0.12 (moderate)
10-13 min          0.18 (useful)
13-15 min          0.25 (strong — resolution anchoring)
```

Near resolution, OFI becomes more informative because price is converging to the settlement value. The remaining uncertainty is resolving, and each trade carries more information about the outcome.

---

## 5. Microprice and Fair Value Estimation

### Standard Mid vs Microprice

The standard mid price:
```
mid = (best_bid + best_ask) / 2
```

The microprice adjusts for depth imbalance:
```
microprice = (best_bid × ask_size + best_ask × bid_size) / (bid_size + ask_size)
```

When bid depth >> ask depth, the microprice shifts toward the ask (the market "wants" to go up). When ask depth >> bid depth, microprice shifts toward the bid.

### Microprice as a Leading Indicator

From empirical analysis:
```
Microprice - Mid    Future 30s Move    Interpretation
────────────────────────────────────────────────────────
> +0.5¢             +0.3 to +0.8¢     Depth predicts direction
+0.1 to +0.5¢      +0.1 to +0.3¢     Mild signal
-0.1 to +0.1¢      No signal          Balanced book
-0.5 to -0.1¢      -0.1 to -0.3¢     Mild signal
< -0.5¢            -0.3 to -0.8¢     Depth predicts direction
```

**The microprice is a ~30-second leading indicator of price direction.** It captures the information embedded in depth imbalance that the simple mid price misses.

---

## 6. Resolution Behavior

### The Resolution Convergence Pattern

In the final 2-3 minutes of a BTC 15-min window, the price exhibits a distinctive pattern:

```
Phase 1 (3-2 min before close): Price oscillates, spread begins widening
Phase 2 (2-1 min before close): Price commits to direction, momentum accelerates
Phase 3 (1-0.5 min before close): Price approaches 0 or 1, spread > 10 cents
Phase 4 (final 30 sec): Illiquid — few participants willing to trade
Phase 5 (resolution): Settlement at 0 or 1
```

### Price Path Statistics Near Resolution

```
Seconds Before Close    % of Windows Where Price > 0.80 or < 0.20
──────────────────────────────────────────────────────────────────
120 sec                 35%
60 sec                  55%
30 sec                  72%
15 sec                  85%
5 sec                   93%
```

**Resolution is gradual, not instantaneous.** The price moves toward its settlement value over the final 2 minutes, creating a "convergence funnel" that narrows as time expires.

### Pre-Resolution Dips

A recurrent pattern in BTC 15-min markets: price **dips briefly** before ultimately resolving in the original direction. This occurs in approximately 30-40% of windows.

```
Example:
  BTC trending UP for 12 minutes → YES price at 0.72
  13:00 — YES dips to 0.65 (temporary reversal)
  13:30 — YES recovers to 0.75
  14:30 — YES settles at 0.95 (UP resolution)
```

The pre-resolution dip creates opportunities for contrarian strategies that buy dips in established trends.

---

## 7. Cross-Exchange Signals

### Polymarket vs CEX Divergence

BTC prediction market prices on Polymarket should track the underlying BTC spot price (since the outcome is determined by BTC price movement). In practice, there are lead-lag relationships:

```
Signal Source         Lead Time vs Polymarket Price
──────────────────────────────────────────────────
Binance BTC/USDT     2-5 seconds ahead
Coinbase BTC/USD     1-3 seconds ahead
Polymarket YES/NO    Reference (lagging)
```

**Polymarket lags the spot market by 2-5 seconds.** This is a structural inefficiency caused by:
1. Human participants who react slower than exchange APIs
2. Market makers who update quotes with deliberate delay (protecting against adverse selection)
3. Blockchain latency for order submission

### USDT Premium Effect

Exchanges quoting BTC/USDT vs BTC/USD can diverge by 0.1-0.3% during market stress (USDT premium/discount). Since Polymarket settles in USDC (which tracks USD), USDT-denominated exchange prices need adjustment:

```
effective_btc_usd = binance_btc_usdt × (1 / usdt_premium)
```

Failing to account for the USDT premium can create phantom signals — apparent divergence that is actually stablecoin basis.

---

## 8. Practical Implications

### For Market Makers
1. **Quote wider near resolution** — adverse selection risk increases exponentially in the final 2 minutes
2. **Monitor OFI for toxic flow** — OFI > 4 signals aggressive directional flow; reduce exposure
3. **Use microprice, not mid** — depth imbalance is informative; the simple mid ignores it
4. **Account for sweep recovery** — after providing liquidity into a sweep, expect 2-5 seconds before depth normalizes

### For Directional Traders
1. **Lead-lag arbitrage** — Polymarket lags spot by 2-5 seconds; monitor exchange feeds for edge
2. **Pre-resolution dips** — ~35% of windows show a dip before resolution; contrarian buying in the final 3 minutes captures this
3. **Spread asymmetry** — persistent spread imbalance signals directional consensus

### For Researchers
1. **L2 data is information-rich** — depth dynamics contain as much signal as price dynamics
2. **Binary markets have unique microstructure** — the pair invariant (YES+NO=$1) creates dynamics absent in equity markets
3. **Resolution dynamics are predictable** — the convergence funnel and pre-resolution dip patterns are robust statistical features

---

## Data Sources

All observations are based on:
- L2 orderbook captures via Polymarket WebSocket API (~1 snapshot/second)
- Price log from continuous feed recording (YES/NO prices at ~1Hz)
- Fill history from Polymarket Subgraph API (public on-chain data)
- CEX price feeds from Binance, Coinbase, Kraken, OKX via WebSocket
