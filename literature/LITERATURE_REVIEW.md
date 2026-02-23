# Literature Review: Prediction Market Making and Binary Outcome Pricing

A survey of academic and practitioner literature on optimal market making in binary prediction markets, with commentary on how each paper informed my approach.

---

## 1. Optimal Market Making in Binary Prediction Markets

**Core problem:** How should a market maker quote two-sided prices for binary contracts (YES/NO shares that settle at $1/$0) while managing inventory risk?

### Key Insight
Binary prediction markets have a unique structural advantage over traditional equity market making: **the two outcomes are perfectly negatively correlated**. A complete YES+NO pair always pays $1 at resolution. This means inventory risk can be managed by maintaining balanced positions rather than by hedging with external instruments.

### Implications for Practice
- The "spread" in binary markets is YES_price + NO_price - 1.0 (the pair cost premium)
- A risk-neutral market maker would quote at fair value + ε on both sides, earning the spread on each matched pair
- In practice, adverse selection (informed traders pushing prices) and inventory imbalance create the real challenge

---

## 2. Static Ladder Strategies in Binary Markets

**Framework:** Place limit orders at fixed price levels on both YES and NO sides, accumulating pairs through passive fills.

### Why Ladders Work for Binaries
Unlike equity market making where inventory is single-directional, binary market makers can hold inventory in *two* offsetting instruments. A static ladder naturally accumulates pairs if the price oscillates around fair value:
- Price rises → YES bids get filled (accumulate YES)
- Price falls → NO bids get filled (accumulate NO)
- Net result: balanced YES+NO pairs accumulated at favorable combined cost

### Level Spacing Trade-offs
- **Tight spacing** (1 cent): High fill rate, low edge per fill, requires high volume for profitability
- **Wide spacing** (3-5 cents): Low fill rate, high edge per fill, vulnerable to directional trends
- **Optimal spacing** depends on expected volatility and window duration

### Practical Finding
From my analysis of on-chain market maker behavior, the dominant participants use 1-3 cent spacing with 5-10 levels per side — consistent with the theoretical prediction for 15-minute binary markets with typical BTC volatility.

---

## 3. Optimal Pair Accumulation in Binary Prediction Markets

**Problem formulation:** Given a binary market with finite duration T, what is the optimal rate of pair accumulation to maximize expected profit while controlling for orphan risk (unmatched shares at resolution)?

### The Orphan Problem
The central risk in binary market making: if you accumulate 500 YES and 300 NO shares, the 200 unmatched YES shares are a *directional bet*. They're worth $200 if the outcome is YES, $0 if NO. This orphan exposure is what makes market making in binaries different from spread capture in continuous markets.

### Optimal Control Approach
The problem can be formulated as an HJB (Hamilton-Jacobi-Bellman) optimal control problem:
- **State:** (YES_shares, NO_shares, time_remaining)
- **Control:** Bid/ask prices at each level (determines fill rate)
- **Objective:** Maximize expected payout - cost, subject to inventory constraints
- **Key result:** Optimal bid is more aggressive on the deficit side (if you have more YES than NO, bid more aggressively for NO)

### Factorization Theorem
The optimal bid for each side can be factored into:
```
optimal_bid = fair_value - spread_component + inventory_adjustment
```
Where inventory_adjustment is proportional to the imbalance m̃ = UP_shares - DN_shares.

### How This Informed My Work
The theoretical framework validates the empirical observation from my market maker analysis: dominant MMs become more aggressive (tighter bids, willing to cross spread) on the deficit side as imbalance grows. The theory predicts the behavior I observed.

---

## 4. Self-Exciting Point Processes (Hawkes Processes)

**Application:** Modeling tweet arrival rates for event prediction on Polymarket.

### Why Hawkes Processes for Social Media Events
Standard Poisson processes assume a constant arrival rate — tweets arrive at some average rate λ. But social media activity is **self-exciting**: one tweet triggers reactions, quote-tweets, and follow-up tweets, creating bursts of activity. The Hawkes process captures this:

```
λ(t) = μ + Σ α × exp(-β × (t - tᵢ))
```

Where:
- μ = background rate (baseline tweeting frequency)
- α = self-excitement parameter (how much each tweet boosts the rate)
- β = decay rate (how quickly the excitement fades)

### Practical Insights
- **Burst detection**: When λ(t) >> μ, we're in a burst regime. This changes the forecast distribution dramatically.
- **Horizon dependence**: Hawkes processes are most informative at medium horizons (24-72h). At short horizons, linear extrapolation dominates. At long horizons, mean reversion dominates.
- **In ensemble models**: Hawkes provides the "burst-aware" component that other models (Poisson, Negative Binomial) miss. Its contribution is highest in high-activity regimes.

---

## 5. Proper Scoring Rules and Probability Calibration

**Why this matters:** A prediction market trading strategy must produce well-calibrated probability estimates. If your model says "60% chance of >200 tweets" but the actual frequency is 45%, you'll systematically overbuy and lose money.

### Key Scoring Rules

**Brier Score:**
```
BS = (1/N) Σ (pᵢ - oᵢ)²
```
Quadratic penalty for miscalibration. Simple, interpretable, but doesn't strongly penalize confident wrong predictions.

**Negative Log-Likelihood (NLL):**
```
NLL = -(1/N) Σ [oᵢ log(pᵢ) + (1-oᵢ) log(1-pᵢ)]
```
Logarithmic penalty — heavily penalizes confident wrong predictions. This is the "sharp" scoring rule: it rewards both calibration AND sharpness (making confident predictions when warranted).

**Expected Calibration Error (ECE):**
```
ECE = Σ |bin_count/N| × |avg_predicted - avg_actual| per bin
```
Groups predictions into bins by confidence level and measures the gap between predicted and actual frequencies. Directly measures calibration without rewarding sharpness.

### Practical Application
In my ensemble model work, I use NLL as the primary optimization objective (it's a proper scoring rule that incentivizes honest probability reporting) and ECE as a diagnostic (to check calibration by horizon). Temperature scaling per model adjusts confidence without changing ranking.

---

## 6. Kelly Criterion and Position Sizing

**The bridge between probability estimation and trading:** Given a probability estimate and a market price, how much should you bet?

### Kelly Formula for Binary Markets
```
f* = (p - p_market) / (1 - p_market)
```
Where:
- p = your model's probability
- p_market = the market price
- f* = optimal fraction of bankroll to wager

### Why Fractional Kelly
Full Kelly is **too aggressive** in practice:
1. **Parameter uncertainty**: Your probability estimate has error bars. Full Kelly assumes perfect knowledge.
2. **Non-ergodicity**: A sequence of Kelly bets can experience large drawdowns that are psychologically or practically intolerable.
3. **Model risk**: If your model is systematically miscalibrated, full Kelly amplifies the error.

In practice, **quarter-Kelly to half-Kelly** provides 75-87.5% of the long-run growth rate with dramatically lower variance and drawdown risk.

### My Implementation
The ensemble model produces probability distributions, not point estimates. This allows computing not just edge (p_model - p_market) but also edge *uncertainty* (σ_edge). The noise-adjusted confidence score:
```
confidence = edge / (edge + σ_edge)
```
Naturally reduces position size when the edge estimate is uncertain, achieving a similar effect to fractional Kelly but calibrated to the specific situation.

---

## 7. Hidden Markov Models for Market Regime Detection

**Application:** Classifying market conditions to gate trading activity (trade only in favorable regimes).

### Why HMMs for Prediction Markets
Binary markets exhibit distinct behavioral regimes:
- **Trending**: Directional moves with momentum carry-through
- **Mean-reverting**: Oscillation around fair value (ideal for market making)
- **Volatile/choppy**: Large moves without persistence (dangerous for both momentum and mean-reversion)
- **Resolved**: Price converges to 0 or 1 near expiry (no trading opportunity)

### Feature Vector
An effective regime detector for 15-minute binary markets uses:
1. Price volatility (std of returns)
2. Trend strength (linear slope)
3. Sign persistence (fraction of returns in same direction)
4. Autocorrelation (lag-1 of returns)
5. Price range (high - low)
6. Bid-ask spread
7. Directional move (final - initial)
8. Mean absolute return (activity level)

### Practical Finding
From backtesting regime-gated strategies: **trading only in "trending" or "mean-reverting" regimes** (avoiding "volatile/choppy") improves Sharpe ratio by 0.3-0.5, primarily by avoiding the worst-performing windows rather than by improving the best ones. The value of regime detection is more about *loss avoidance* than *gain enhancement*.

---

## 8. Chapman-Kolmogorov Forward Equations

**Application:** Predicting future count distributions (e.g., tweet count at market close) from a time-varying intensity process.

### The Problem
Given a Poisson process with time-varying rate λ(t) — where the rate depends on hour-of-day patterns, recent activity, and self-exciting dynamics — compute the probability distribution of the total count at time T.

### Approach
The Chapman-Kolmogorov forward equation:
```
dP(n,t)/dt = λ(t) × [P(n-1,t) - P(n,t)]
```
This ODE system propagates the probability mass function forward in time, accounting for the time-varying rate. Solved numerically using RK45 (Runge-Kutta 4th-5th order adaptive).

### Why This Matters
Standard approaches (fixed-rate Poisson, simple extrapolation) assume stationarity. Real tweet patterns are highly non-stationary:
- Circadian rhythm (tweets clustered in waking hours)
- Self-excitement (bursts trigger more bursts)
- Day-of-week effects

The TVP (Time-Varying Poisson) model with Fourier-decomposed hour-of-day modulation captures these patterns:
```
λ(t) = exp(β₀ + Σₖ [aₖ sin(2πkt/24) + bₖ cos(2πkt/24)])
```

---

## 9. Markov-Modulated Poisson Processes (MMPP)

**Application:** Modeling latent activity states (quiet vs. burst) for tweet count prediction.

### The Model
An MMPP combines a hidden Markov chain (states: quiet, active, burst) with state-dependent Poisson rates:
```
State 1 (quiet):  λ₁ = 0.5 tweets/hour
State 2 (active): λ₂ = 3.0 tweets/hour
State 3 (burst):  λ₃ = 15.0 tweets/hour
```
The system transitions between states with rates determined by the transition matrix Q.

### Complementarity with Hawkes
MMPP and Hawkes processes model the same phenomenon (burstiness) from different perspectives:
- **Hawkes**: Bottom-up — each event excites the rate
- **MMPP**: Top-down — latent state determines the rate regime

In practice, they capture different aspects of the dynamics and provide orthogonal predictions, making them valuable ensemble components.

---

## 10. Ensemble Methods and Model Diversity

**The meta-finding:** No single model dominates across all horizons and regimes. The key to robust probability estimation is ensembling diverse models with time-aware weighting.

### Model Contributions by Horizon

| Model | Best At | Worst At | Contribution |
|-------|---------|----------|--------------|
| Linear extrapolation | 0-12h (simple, low noise) | >48h (misses dynamics) | Baseline |
| Negative Binomial | 24-96h (overdispersion) | 0-6h (overkill) | Tail coverage |
| Hawkes | 12-72h (burst dynamics) | >96h (overfitting to recent) | Burst awareness |
| Poisson-Gamma | >48h (Bayesian shrinkage) | 0-12h (too conservative) | Long-horizon stability |
| TVP | 6-24h (circadian patterns) | >72h (pattern drift) | Time-of-day adjustment |
| MMPP | All horizons (regime capture) | N/A | Regime complementarity |

### Weighting Strategy

**Sigmoid regime blending** — the ensemble uses time-dependent weights that transition smoothly between regimes:
```
w(τ) = w_max / (1 + exp(-k × (τ - τ_mid)))
```
Where τ is the time remaining. This ensures that near-term predictions are dominated by the most accurate short-horizon model (linear), while long-horizon predictions blend in the more sophisticated distributional models.

### Temperature Calibration

Each model's confidence is calibrated via temperature scaling:
```
p_calibrated = σ(logit(p_raw) / T)
```
Where T is learned per model via cross-validation. Models that are overconfident (T > 1) get softened; underconfident models (T < 1) get sharpened. This is critical for proper scoring — raw ensemble outputs are often overconfident.

---

## Cross-Cutting Themes

### Theme 1: The Pair Structure is Unique
Binary prediction markets have a mathematical structure (YES + NO = $1) that doesn't exist in equity markets. This enables market-neutral strategies (pair accumulation) that are structurally different from traditional market making.

### Theme 2: Calibration Beats Accuracy
A well-calibrated model that says "60%" when the true probability is 60% is more valuable than a sharp model that says "80%" when the truth is 60%. Trading profits come from **correct probability estimation**, not from being "right" about direction more often.

### Theme 3: Regime Awareness Matters
Both market making and directional trading benefit from regime detection. The same strategy that works in calm, mean-reverting markets will fail in volatile, trending ones. The academic literature on regime-switching (HMM, MMPP) provides the framework for this.

### Theme 4: The Ensemble is the Edge
No single model dominates. The edge comes from combining diverse approaches with proper weighting and calibration. This is consistent with the broader ML literature on ensemble methods (bagging, boosting, stacking) but applied to the specific domain of probability estimation.

---

## Further Reading

For practitioners entering prediction markets, the most impactful areas to study (in order):
1. Kelly criterion and bankroll management (the bridge between model and P&L)
2. Proper scoring rules (how to evaluate and calibrate probability estimates)
3. Hawkes processes (fundamental for event-driven prediction markets)
4. Pair accumulation theory (the mathematical foundation of binary market making)
5. HMM regime detection (knowing when NOT to trade is as valuable as knowing when to trade)
