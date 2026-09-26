#!/usr/bin/env python3
"""Play Grit (fast) vs simple opponents; print W-D-L and a rough Elo band."""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

import chess

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.engine import StockfishEngine  # noqa: E402
from app.models import MoveRequest  # noqa: E402
from app.policies import choose_move  # noqa: E402


def random_move(board: chess.Board) -> chess.Move:
    return random.choice(list(board.legal_moves))


def capture_random(board: chess.Board) -> chess.Move:
    caps = [m for m in board.legal_moves if board.is_capture(m)]
    return random.choice(caps) if caps else random_move(board)


def opponent_move(
    engine: StockfishEngine,
    board: chess.Board,
    kind: str,
) -> chess.Move:
    if kind == "random":
        return random_move(board)
    if kind == "capture_random":
        return capture_random(board)
    if kind == "bad":
        req = MoveRequest(fen=board.fen(), difficulty="bad", fast=True, movetime_ms=50)
        return choose_move(engine, board, req).move
    if kind.startswith("skill"):
        level = int(kind.split(":")[1])
        return engine.play(board, movetime_ms=50, skill_level=level)
    if kind.startswith("elo"):
        elo = int(kind.split(":")[1])
        return engine.play(board, movetime_ms=50, elo=elo, limit_strength=True)
    raise ValueError(kind)


def play_game(engine: StockfishEngine, opp: str, grit_white: bool) -> str:
    board = chess.Board()
    ply = 0
    while not board.is_game_over() and ply < 180:
        is_grit = (board.turn == chess.WHITE) == grit_white
        if is_grit:
            req = MoveRequest(
                fen=board.fen(),
                difficulty="grit",
                fast=True,
                movetime_ms=40,
                win_horizon=4,
            )
            move = choose_move(engine, board, req).move
        else:
            move = opponent_move(engine, board, opp)
        board.push(move)
        ply += 1

    result = board.result(claim_draw=True)
    if result == "1-0":
        return "W" if grit_white else "L"
    if result == "0-1":
        return "L" if grit_white else "W"
    return "D"


def rough_elo(wins: int, draws: int, losses: int, opp_elo: int) -> int:
    n = wins + draws + losses
    if n == 0:
        return opp_elo
    score = (wins + 0.5 * draws) / n
    # Invert logistic roughly: score ≈ 1/(1+10^((opp-elo)/400))
    # elo ≈ opp - 400 * log10(1/score - 1)
    if score <= 0.01:
        return opp_elo - 400
    if score >= 0.99:
        return opp_elo + 400
    import math

    return int(opp_elo - 400 * math.log10(1 / score - 1))


OPP_ELO = {
    "random": 600,
    "capture_random": 800,
    "bad": 900,
    "skill:0": 1000,
    "skill:3": 1200,
    "skill:5": 1400,
    "elo:1320": 1320,
    "elo:1600": 1600,
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--games", type=int, default=6, help="Games per opponent")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    random.seed(args.seed)

    engine = StockfishEngine()
    engine.start()

    opponents = [
        "random",
        "capture_random",
        "bad",
        "skill:0",
        "skill:3",
        "skill:5",
        "elo:1320",
        "elo:1600",
    ]

    print(f"{'opponent':<16} {'W-D-L':<10} {'score':>6} {'~elo':>6}")
    print("-" * 44)
    try:
        for opp in opponents:
            results = []
            for i in range(args.games):
                grit_white = i % 2 == 0
                results.append(play_game(engine, opp, grit_white))
            w = results.count("W")
            d = results.count("D")
            l = results.count("L")
            score = (w + 0.5 * d) / max(1, len(results))
            elo = rough_elo(w, d, l, OPP_ELO[opp])
            print(f"{opp:<16} {w}-{d}-{l:<6} {score:>6.2f} {elo:>6}")
    finally:
        engine.close()


if __name__ == "__main__":
    main()
