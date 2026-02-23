# Market Maker Analysis

Reverse-engineering the behavior of Polymarket's most active market makers using publicly visible on-chain trade data and L2 orderbook snapshots.

## Motivation

On a traditional exchange, market maker activity is hidden behind anonymized order IDs. On Polymarket (Polygon blockchain), every fill is attributed to a wallet address. This means we can:

1. Identify the most active liquidity providers by volume
2. Reconstruct their order placement strategy from fill patterns
3. Infer their inventory management rules from aggression triggers
4. Evaluate their edge (or lack thereof) from outcomes

This is *exactly* the kind of analysis that institutional desks (SIG, Jump, DRW) perform when entering a new venue. Understanding the existing liquidity landscape is a prerequisite for deploying capital.

## Methodology

### Step 1: Wallet Identification
Using Polymarket's Subgraph API, identify wallets with the highest fill counts on BTC 15-minute markets. The top wallets show 2,000-5,000 fills per month — clearly algorithmic.

### Step 2: L2 Fingerprinting (`fingerprint_ladder.py`)
For each known fill from a target wallet:
- Find the L2 book snapshot immediately before and after the fill
- Diff the book at the fill price to identify vanishing quantity
- Classify as maker (resting order got filled) or taker (crossed the spread)
- Catalog order sizes to identify distinctive size signatures

### Step 3: Edge Decomposition (`analyze_edge.py`)
Match each fill against real-time price data to compute:
- **Execution edge**: fill_price vs market_mid (did they fill better than mid?)
- **Selection edge**: which windows they skip (skip rate correlates with conditions)
- **Timing edge**: entry/exit timing within windows
- **Aggression triggers**: what state variables cause spread-crossing

## Key Findings

See [docs/FINDINGS.md](docs/FINDINGS.md) for the full write-up.

## Data Pipeline

```
Polymarket Subgraph API          L2 WebSocket Capture
     │ (fill history)                │ (orderbook snapshots)
     ▼                               ▼
  trades.json                    data/l2/*.jsonl.gz
     │                               │
     └───────────┬───────────────────┘
                 │
        fingerprint_ladder.py
                 │
                 ▼
        Fill Classification
     (maker/taker, sizes, levels)
                 │
                 ▼
          analyze_edge.py
                 │
                 ▼
     Edge Decomposition Report
```
