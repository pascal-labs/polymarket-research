# polymarket-research

Independent research into prediction market microstructure, market maker behavior, and the emerging institutional landscape. This repo documents my analytical methodology for studying how binary outcome markets actually work — from L2 orderbook dynamics to the strategies of the largest on-chain market makers.

## Why This Exists

Prediction markets are undergoing a phase transition. Combined volume grew from ~$9B (2024) to $76B+ (2025), driven by institutional market makers (SIG, Jump, Jane Street, DRW) entering what was previously a retail-dominated space. Understanding the microstructure of these markets — how liquidity forms, how spreads behave around resolution, how professional market makers structure their ladders — is the foundation for any serious quantitative approach.

This isn't a trading system. It's the research that informs one.

## Architecture

```
polymarket-research/
│
├── market-maker-analysis/           # Reverse-engineering on-chain MM behavior
│   ├── fingerprint_ladder.py        # L2 orderbook diff analysis
│   ├── analyze_edge.py              # Edge quantification framework
│   └── docs/
│       └── FINDINGS.md              # Detailed write-up of discoveries
│
├── literature/
│   └── LITERATURE_REVIEW.md         # Academic papers on binary market making
│
├── microstructure/
│   └── ORDERBOOK_DYNAMICS.md        # Empirical observations on CLOB behavior
│
└── ecosystem/
    └── ECOSYSTEM_OVERVIEW.md        # Industry map: platforms, players, strategies
```

## Research Areas

### 1. Market Maker Fingerprinting

Polymarket's on-chain transparency means every trade from every wallet is public. I used L2 orderbook diffs to reconstruct the ladder strategies of the most active market makers — analyzing fill sizes, level spacing, maker/taker ratios, and replenishment patterns. The methodology is applicable to any on-chain CLOB.

**Key insight:** The dominant market makers use static ladder strategies with DCA-style accumulation, but their aggression triggers are state-dependent — they cross the spread when position imbalance exceeds specific thresholds late in the window.

### 2. Orderbook Microstructure

Empirical analysis of how Polymarket's CLOB behaves:
- Spread dynamics across market types (BTC 15-min vs political vs sports)
- Liquidity depth patterns by time of day and proximity to resolution
- Queue replenishment rates after sweeps
- The relationship between order flow imbalance and short-term price direction

### 3. Literature Review

Survey of academic work on optimal market making in binary prediction markets, including ladder strategies, pair accumulation under inventory constraints, and proper scoring rules for probability calibration.

### 4. Ecosystem Analysis

Comprehensive mapping of the prediction market industry as of early 2026 — platforms, institutional participants, regulatory landscape, and the seven key strategies being deployed by professional trading firms.

## Methodology

All analysis uses publicly available on-chain data. Wallet activity on Polygon is transparent by design — the trades analyzed here are visible to anyone running a block explorer. The analytical value isn't in the data (it's public), it's in the framework for interpreting it.

**What's included:** Analytical methodology, research findings, code for data processing.

**What's excluded:** My own trading parameters, wallet addresses, position sizes, and live strategy configuration.

## Data Requirements

The analysis scripts expect:
- L2 orderbook snapshots (JSONL.gz format from WebSocket capture)
- Trade history (JSON, fetched via Polymarket Subgraph API)
- Price log (CSV with timestamp, yes_price, no_price per market)

These data files are not included in the repo (too large, and continuously regenerated from live capture).

## Related Projects

- [polymarket-sdk](https://github.com/pascal-labs/polymarket-sdk) — Python SDK for Polymarket API interaction
- [pulsefeed](https://github.com/pascal-labs/pulsefeed) — Multi-exchange crypto price aggregation
- [event-probability-models](https://github.com/pascal-labs/event-probability-models) — Ensemble probability models for prediction markets

## License

MIT
