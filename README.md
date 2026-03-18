# Esports Polymarket Trading Bot

Automated trading bot that discovers esports markets on Polymarket, computes fair odds using multiple pricing approaches, and places orders via the CLOB API.

## Architecture

```
SCHEDULER (async loop, every 5 min)
  |                        |
DATA INGEST          POLYMARKET SCANNER
(HLTV, PandaScore,   (Gamma API → events,
 VLR.gg, OddsPapi)    CLOB API → order books)
  |                        |
  +----> PRICING ENGINE <--+
         (Pinnacle arb, Glicko-2, cross-market)
                |
         EXECUTION ENGINE
         (py-clob-client → limit/market orders)
                |
         RISK MANAGER
         (Kelly sizing, kill switches, exposure limits)
```

## Supported Games

| Game       | Data Source     | Gamma Sport ID | OddsPapi Sport ID |
|------------|-----------------|----------------|--------------------|
| CS2        | HLTV            | 37             | 17                 |
| Dota 2     | PandaScore      | 38             | 16                 |
| LoL        | PandaScore      | 39             | 18                 |
| Valorant   | VLR.gg          | 40             | 61                 |

## Pricing Approaches

1. **Pinnacle Fair Value (odds_arb)** — Strips vig from Pinnacle lines and compares to Polymarket prices
2. **Glicko-2 Model (elo_model)** — Maintains team ratings and predicts BO1/BO3/BO5 outcomes
3. **Cross-Market Checks (cross_market)** — Detects inconsistencies between moneyline, handicap, and total sub-markets

## Setup

### 1. Clone and install

```bash
git clone <repo-url>
cd esports-polymarket-bot
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env with your API keys
```

Required keys:
- `POLYMARKET_PRIVATE_KEY` — Polygon wallet private key (for live trading)
- `ODDSPAPI_API_KEY` — Free key from OddsPapi

Optional keys:
- `PANDASCORE_API_KEY` — Free tier, 1000 req/hr

### 3. Run (dry-run mode)

```bash
python main.py
```

The bot starts in **dry-run mode** by default — it scans markets, computes signals, and logs everything, but does **not** place real orders.

### 4. Go live

```bash
# In your .env file:
DRY_RUN=false
```

**Warning:** Live mode places real orders with real money on Polymarket. Start with small limits.

## Risk Parameters

| Parameter                     | Default | Description                        |
|-------------------------------|---------|------------------------------------|
| `RISK_MAX_POSITION_PER_MATCH` | $100    | Max position per match             |
| `RISK_MAX_TOTAL_EXPOSURE`     | $500    | Max total exposure across all      |
| `RISK_MAX_DAILY_LOSS`         | $50     | Daily loss kill switch             |
| `RISK_MIN_EDGE_THRESHOLD`     | 0.03    | Minimum 3-cent edge to trade       |
| `RISK_MAX_MATCHES_CONCURRENT` | 10      | Max simultaneous match positions   |

## Running Tests

```bash
python -m pytest tests/ -v
```

## Project Structure

```
├── config.py              # Environment-based configuration
├── scanner.py             # Polymarket market discovery
├── execution.py           # CLOB order placement
├── risk.py                # Position sizing & kill switches
├── main.py                # Async scheduler loop
├── db.py                  # SQLite persistence
├── data_ingest/
│   ├── hltv_client.py     # CS2 data (hltv-async-api)
│   ├── lol_client.py      # LoL data (PandaScore)
│   ├── valorant_client.py # Valorant data (vlrdevapi + REST)
│   ├── odds_client.py     # Pinnacle odds (OddsPapi)
│   └── pandascore.py      # Multi-game schedules & stats
├── pricing/
│   ├── odds_arb.py        # Approach A: Pinnacle fair value
│   ├── elo_model.py       # Approach B: Glicko-2 ratings
│   └── cross_market.py    # Approach C: Sub-market consistency
├── tests/
│   ├── test_risk.py
│   ├── test_pricing.py
│   └── test_scanner.py
├── requirements.txt
├── .env.example
└── README.md
```
