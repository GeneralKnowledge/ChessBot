# ChessBot

Stateless FastAPI service that wraps **Stockfish** so clients never embed the engine. Primary personality: **Grit** — a pawn-heavy trickster that baits greed and only trusts Stockfish when the win is obvious.

## Stack

- FastAPI + `python-chess` + Stockfish UCI
- Env: `STOCKFISH_PATH` (default `/usr/games/stockfish`)
- Thread-safe engine wrapper; restarts Stockfish on UCI/desync errors

## Quick start

```bash
# System Stockfish (Debian/Ubuntu)
sudo apt-get install -y stockfish

python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

uvicorn app.main:app --reload --port 8000
```

### Docker (recommended for servers)

Stockfish is installed inside the image — no host engine needed.

**Compose (easiest on a VPS):**

```bash
cp .env.example .env   # optional: edit PORT / GRIT_PAWN_BIAS
docker compose up -d --build
curl -s http://localhost:8000/health
```

**Plain Docker:**

```bash
docker build -t chessbot .
docker run -d --name chessbot --restart unless-stopped -p 8000:8000 chessbot
```

Useful commands:

```bash
docker compose logs -f          # follow logs
docker compose down             # stop
docker compose up -d --build    # rebuild after git pull
```

Put a reverse proxy (Caddy/nginx) in front if you want HTTPS on a public domain.

## API

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/health` | Engine alive |
| `POST` | `/move` | Choose a move (+ reason / eval) |
| `POST` | `/analyze` | Short MultiPV analysis (no personality) |

### `POST /move` — Grit

```bash
curl -s http://localhost:8000/move \
  -H 'content-type: application/json' \
  -d '{
    "fen": "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
    "difficulty": "grit",
    "prefer_piece": null,
    "win_horizon": 5
  }' | jq
```

Example response shape:

```json
{
  "move": "e2e4",
  "san": "e4",
  "reason": "grit_pawn",
  "difficulty": "grit",
  "fen": "...",
  "fen_after": "...",
  "eval": {"unit": "cp", "value": 25},
  "pv": ["e2e4", "e7e5"],
  "resign_guess": null,
  "draw_guess": null,
  "metadata": {"pawn_bias": 65}
}
```

Mate-in-1 example:

```bash
curl -s http://localhost:8000/move \
  -H 'content-type: application/json' \
  -d '{"fen":"6k1/5ppp/8/8/8/8/8/4Q1K1 w - - 0 1","difficulty":"grit"}' | jq
# reason: grit_coup
```

### Difficulties

| id | behavior |
|----|----------|
| `best` | Stockfish best (Skill 20) |
| `skill` | UCI `Skill Level` (`skill_level`, default 5) |
| `elo` | `UCI_LimitStrength` + `UCI_Elo` (SF16 floor **1320**) |
| `bad` | Among-worst MultiPV; honors `prefer_piece` |
| `rebellion` | Pawn-first; free captures; mates within horizon |
| **`grit`** | See below (`pocket_sand` alias) |

Optional body fields: `prefer_piece`, `win_horizon`, `movetime_ms`, `multipv`, `fast`, `move_number`, `skill_level`, `elo`.

### `POST /analyze`

```bash
curl -s http://localhost:8000/analyze \
  -H 'content-type: application/json' \
  -d '{"fen":"rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1","multipv":3}' | jq
```

## Grit

Personality: pawn-heavy trickster that beats careless play, loses to real engines; bait and punish greed; only trust Stockfish when the win is obvious.

Priority: **coup → defend → free capture → bait/threat/punish → MultiPV + soft pawn bias**.

| Reason tag | Meaning |
|------------|---------|
| `grit_coup` | Forced mate within `win_horizon` |
| `grit_defend` | Stop mating attack (no pawn-into-mate) |
| `grit_capture` | Free / winning capture (~≥100cp SEE) |
| `grit_bait` | Offer a piece; take → mate ≤2 or major win |
| `grit_threat` | Mate-in-2 style pressure |
| `grit_punish` | Punish greed on hanging material |
| `grit_obvious` | Mate forced or MultiPV gap ≥ ~250cp |
| `grit_pawn` / `grit_quiet` | Soft bias among candidates (not pawn autopilot) |

Tune with `GRIT_PAWN_BIAS` (default `65`).

## Tests

```bash
pytest -q
```

## Elo probe (optional)

```bash
python scripts/elo_probe.py --games 4
```

Plays Grit (`fast=True`) vs random / capture-random / `bad` / Skill 0/3/5 / Elo 1320/1600 and prints W-D-L + a rough Elo band.
