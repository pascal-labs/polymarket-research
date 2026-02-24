# Methodology: Fingerprinting a Market Maker from Public Data

How I identified, tracked, and reverse-engineered a professional market maker operating on Polymarket's BTC 15-minute binary markets — using only publicly available on-chain data.

---

## Data Collection Pipeline

### 1. Trade History (Polymarket Data API)

Every Polymarket trade settles on-chain (Polygon), which means every fill is attributed to a specific wallet address. The data API exposes this:

```
GET https://data-api.polymarket.com/activity?user={WALLET}&type=TRADE&limit=500&offset=0
```

**Challenge:** The API limits responses to 500 trades per request, and large wallets have 40,000+ trades.

**Solution:** Paginated fetching with offset windowing. For wallets that exceed the API's offset limit (~10,000), I switch to timestamp-based windowing. For large wallets, backward timestamp pagination using the `end=` API parameter is more reliable than offset-based pagination. The API returns trades in reverse chronological order, so `end=<min_timestamp>` fetches the next page going backwards — fetching the most recent batch, noting the earliest timestamp, then requesting trades before that timestamp.

**Output:** Complete fill history in JSON — timestamp, price, size, side (BUY/SELL), outcome (Up/Down), market slug, USDC amount.

### 2. L2 Orderbook Snapshots (WebSocket Capture)

Polymarket's WebSocket API streams full L2 orderbook state at ~1 snapshot/second per market. I built a capture pipeline that:

- Subscribes to all active BTC 15-min markets simultaneously
- Records every book update as a JSONL line (compressed to .jsonl.gz per market)
- Captures both `book` events (full depth snapshots) and `trade` events (fills)

Each snapshot contains the full bid/ask depth at every price level — not just best bid/offer, but the complete ladder.

**Data format:** `{asset: "up"|"dn", event: "book"|"trade", ts: float, bids: [[price, size], ...], asks: [[price, size], ...]}`

### 3. Price Log (Continuous Feed)

A separate recorder captures YES/NO prices at ~1Hz for every active market. This creates a dense price timeline for computing execution quality (fill price vs. market mid at exact fill timestamp).

**Format:** CSV with columns `timestamp, market_id, yes_price, no_price, spread`

---

## L2 Completeness Pipeline

Not all captured L2 windows are suitable for analysis. Before matching trades to orderbook data,
each L2 capture undergoes completeness filtering:

### Criteria

| Check | Threshold | Rationale |
|-------|-----------|-----------|
| Minimum duration | >= 850 seconds | 15-min window = 900s; 850s allows for slight startup delay |
| Maximum snapshot gap | <= 5 seconds | Fills between snapshots can't be reliably classified |
| Both sides present | UP and DN book data | Need both orderbooks for imbalance and spread calculations |
| Minimum snapshots | >= 10 | Below this, statistical measures are unreliable |

### Pipeline

1. Load trades from wallet fill history
2. Group trades by market window slug
3. For each slug, check if L2 capture file exists (`{slug}.jsonl.gz`)
4. Load L2 events, build book timeseries
5. Apply completeness filter
6. Output: matched trades (with complete L2) + rejection report

### Rejection Statistics

In a typical capture run, the breakdown is:
- ~40% of windows have no L2 file (capture wasn't running)
- ~30% are rejected for completeness (gaps, short duration, missing side data)
- ~30% pass all filters and are used for analysis

This aggressive filtering means we work with fewer windows but can make stronger claims
about fill classification accuracy.

---

## 4 Fingerprinting Techniques

### Technique 1: Direct API Matching

The simplest approach — pull all fills for a known wallet, group by market window slug.

```
For each wallet:
    trades = fetch_all_trades(wallet)
    by_window = group_by(trades, key="slug")
    → position trajectory per window (UP shares, DN shares, costs)
```

This gives the complete position history but doesn't tell us whether fills were passive (maker) or aggressive (taker).

### Technique 2: L2 Orderbook Diffing

The core fingerprinting technique. For each fill:

1. Find the L2 book snapshot immediately **before** the fill timestamp
2. Find the L2 book snapshot immediately **after** the fill timestamp
3. Diff the book at the fill price level
4. **Vanishing quantity = the resting order that got filled**

```
Example:
    Before: asks at $0.52 = 800 shares
    Fill: BUY 200 shares at $0.52
    After: asks at $0.52 = 600 shares
    → Vanished: 200 shares (exact match)
    → Classification: TAKER (consumed ask)

    Before: bids at $0.48 = 200 shares
    Fill: BUY 200 shares at $0.48
    After: bids at $0.48 = 0 shares
    → Vanished: 200 shares from bids (the MM's resting order was hit)
    → Classification: MAKER (passive order filled)
```

**Tolerance:** 80% match between vanished quantity and fill size (accounts for partial fills and timing gaps between snapshots).

**Key insight:** When the vanished-to-fill ratio is exactly 1.0, the market maker was the **sole order** at that price level. This happens in 55-65% of maker fills, meaning their ladder levels are carefully chosen to avoid overlap.

**Note:** An alternative classification method uses the BBO (best bid/offer) at the time of fill: if a BUY fill executes at or above the best ask, it's a taker fill (lifted the offer). If it executes below the best ask, it's a maker fill (resting bid was hit). This method has higher coverage (~99.9% classification rate) than the vanished-quantity method, though it cannot distinguish between fills at the same price level.

### Technique 3: Price-Time Matching

Binary search each fill's timestamp against the price log to compute execution quality:

```
For each fill:
    market_mid = get_nearest_price(price_log, fill.timestamp, max_gap=5s)
    edge = market_mid - fill.price

    edge > 0 → PASSIVE fill (better than market)
    edge < 0 → AGGRESSIVE fill (crossed the spread)
    edge ≈ 0 → AT MARKET
```

This separates fills into passive vs. aggressive without needing L2 data, and quantifies **how much** the MM is paying for urgency when they cross the spread.

### Technique 4: Signature Reconstruction

Aggregate the classified fills across hundreds/thousands of windows to extract stable behavioral signatures:

**Fill size fingerprint:** The distribution of order sizes. Each market maker has a distinctive size signature (e.g., one clusters at ~8 shares/level, another at 200 shares/level). This is as identifying as a fingerprint.

**Ladder structure:** From maker fills, reconstruct the price levels used. Compute level spacing (typically 1-2 cents), number of levels per side (typically 5-10), and how the ladder shifts with inventory.

**Inventory trajectory:** Plot cumulative UP vs DN shares over each window lifecycle. The convergence pattern (how quickly positions balance toward 50/50) reveals the inventory management algorithm.

**Aggression triggers:** Segment aggressive fills by market state (imbalance level, time remaining, spread width). The state variables that predict aggression reveal the MM's implicit risk thresholds.

---

## Why This Works

Three structural features of Polymarket make this analysis possible:

1. **On-chain attribution:** Every trade is permanently linked to a wallet address. Unlike traditional exchanges where order flow is anonymized, the complete trading history of any participant is public.

2. **L2 transparency:** Full orderbook depth is streamed via WebSocket. Fills create observable discontinuities in the book state. By diffing snapshots around fills, we can classify each fill as maker or taker.

3. **Algorithmic consistency:** Professional market makers use systematic strategies that produce identifiable patterns. The same ladder structure, fill sizes, and aggression triggers repeat across thousands of windows — creating a signature that can be extracted statistically.

---

## Limitations

- **Timing resolution:** L2 snapshots arrive at ~1/second. Sub-second dynamics (e.g., two fills in the same second) may be misclassified.
- **Multi-wallet operation:** A single entity may operate multiple wallets, making wallet-level analysis an incomplete picture.
- **Survivorship bias:** This analysis covers active, profitable market makers. Wallets that lost money and stopped trading are not represented.
- **Regime changes:** Market maker behavior may shift as competition evolves or as they update their algorithms.

---

## Data Quality

### L2 Timing Resolution

Book snapshots arrive at ~1 Hz. This creates a fundamental timing limitation:
- Fills that occur between snapshots use the nearest snapshot for classification
- Two fills in the same second may share the same "before" snapshot
- Sub-second book dynamics (quote flickering, fill-then-replace) are invisible

For the BBO classification method, this means ~0.1% of fills may be misclassified
when the BBO changes between the snapshot and the fill timestamp.

### Deduplication

The Polymarket data API's backward pagination can return overlapping trades at page
boundaries. Deduplication uses a composite key of (transaction_hash, condition_id,
outcome_index, side, price, size, timestamp) to eliminate duplicates while preserving
legitimate same-timestamp fills at different prices.

---

## Data Sources

All analysis uses publicly visible data:
- **Fill history:** Polymarket data API (public on-chain trade attribution)
- **L2 orderbook:** Polymarket WebSocket API (public depth data)
- **Price log:** Continuous recording from WebSocket price feeds
- **CEX reference prices:** Binance, Coinbase, Kraken, OKX via public WebSocket APIs
