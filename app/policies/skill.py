"""Skill Level / Elo-limited Stockfish play."""

from __future__ import annotations

import chess

from app.config import get_settings
from app.engine import StockfishEngine
from app.models import MoveRequest
from app.policies.base import PolicyResult


def choose(engine: StockfishEngine, board: chess.Board, req: MoveRequest) -> PolicyResult:
    settings = get_settings()
    movetime = req.movetime_ms or (100 if req.fast else 200)

    if req.difficulty == "elo" or req.elo is not None:
        elo = req.elo or settings.elo_floor
        elo = max(elo, settings.elo_floor)
        move = engine.play(
            board,
            movetime_ms=movetime,
            elo=elo,
            limit_strength=True,
        )
        return PolicyResult(
            move=move,
            reason="elo",
            metadata={"elo": elo, "limit_strength": True},
        )

    skill = req.skill_level if req.skill_level is not None else 5
    move = engine.play(board, movetime_ms=movetime, skill_level=skill)
    return PolicyResult(
        move=move,
        reason="skill",
        metadata={"skill_level": skill},
    )
