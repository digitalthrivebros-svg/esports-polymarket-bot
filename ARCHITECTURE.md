# Esports Polymarket Bot - Full Architecture & Build Guide

## What You Are Trading
Each esports match on Polymarket has multiple sub-markets:
- Moneyline (who wins the series): $50K-$400K volume, best liquidity
- Individual Game Winners (Game 1, 2, 3, 4): $2K-$5K volume each
- Game Handicap (-1.5, -2.5): $10K-$20K volume
- Total Games (over/under 3.5, 4.5): $2K-$5K volume

## System Architecture (5 Modules)
```
SCHEDULER (cron loop, every 5 min)
  |                        |
DATA INGEST          POLYMARKET SCANNER
(external esports    (find open markets)
 feeds)                    |
  |                        |
  +----> PRICING ENGINE <--+
         (compute fair odds, compare to PM)
                |
         EXECUTION ENGINE
         (place/cancel orders via CLOB API)
                |
         RISK & P&L TRACKER
         (position mgmt, kill switches)
```

## API Reference
- Polymarket CLOB API: https://clob.polymarket.com
- Polymarket Gamma API: https://gamma-api.polymarket.com
- Polymarket Docs: https://docs.polymarket.com
- Polymarket Python SDK: pip install py-clob-client
- Polymarket Sports WSS: wss://ws-subscriptions-clob.polymarket.com/ws/sports
- OddsPapi (esports odds): https://api.oddspapi.io/v4
- HLTV Scraper: pip install hltv-async-api
- VLR.gg API: pip install vlrdevapi
- PandaScore: https://api.pandascore.co (free tier, 1000 req/hr)

## Sport IDs for OddsPapi
- 16 = Dota 2
- 17 = Counter-Strike (CS2)
- 18 = League of Legends
- 61 = Valorant
- 65 = Honor of Kings
