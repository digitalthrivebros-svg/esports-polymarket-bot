# API Research Notes (March 17, 2026)

## Polymarket Gamma API
- Base: https://gamma-api.polymarket.com
- Sports configs: GET /sports returns configs for csgo (ID 37), dota2 (ID 38), lol (ID 39), valorant (ID 40)
- Market types: GET /sports/market-types - confirmed CS2 types (cs2_odd_even_total_kills, cs2_odd_even_total_rounds), LoL types (lol_both_teams_baron, etc.), Dota2 types, and general esports types (moneyline, map_handicap, map_participant_win_one, map_participant_win_total, match_handicap, total_games, kill_over_under_game, moba_*, shooter_*, first_blood_game)
- Events: GET /events?tag_slug=esports&active=true returns events but tag-based filtering may not work perfectly for sports; use sports-specific endpoints or tag IDs from sports configs (tags field: 1,64,100780,100639 for csgo etc.)
- Teams: GET /sports/teams
- Each sport has: tags (comma-separated), series ID, resolution source (hltv.org for csgo, liquipedia for others)

## Polymarket CLOB API  
- Base: https://clob.polymarket.com
- GET /book?token_id=<TOKEN> - full order book
- GET /midpoint?token_id=<TOKEN> - midpoint price
- GET /spread?token_id=<TOKEN> - bid/ask spread
- GET /server-time - server time
- GET /orders?market=<CONDITION_ID> - open orders
- DELETE /order/{order_id} - cancel order
- DELETE /orders - cancel all orders
- GET /fee-rate - fee rate
- WSS wss://ws-subscriptions-clob.polymarket.com/ws/sports - live scores
- SDK: py-clob-client (Python) - ClobClient class

## OddsPapi API
- Base: https://api.oddspapi.io
- Requires API key (free tier available, no credit card)
- GET /v4/tournaments?sportId=<ID>&apiKey=<KEY> - list tournaments for a sport
- GET /v4/odds-by-tournaments?bookmaker=pinnacle&tournamentIds=<IDs>&apiKey=<KEY> - get odds
- Sport IDs: 16=Dota2, 17=CS2, 18=LoL, 61=Valorant, 65=Honor of Kings
- Bookmaker param: "pinnacle" for sharpest lines
- oddsFormat param: "decimal" or "american"
- Response includes: fixtureId, participant1Id, participant2Id, sportId, tournamentId, startTime, odds data

## HLTV (CS2)
- pip install hltv-async-api
- get_top_teams(), get_upcoming_matches(days=N), get_match_info(match_id), get_team_info(team_id)

## VLR.gg (Valorant)
- pip install vlrdevapi (Python wrapper)
- vlr.matches.upcoming(), vlr.search.search("team_name")
- REST API: https://vlrggapi.vercel.app/ - GET /match/upcoming, GET /events, GET /match/results

## PandaScore
- Base: https://api.pandascore.co
- Free tier: 1000 req/hr
- Match schedules, tournament brackets, team rosters, stats for LoL, CS2, Dota2, Valorant
