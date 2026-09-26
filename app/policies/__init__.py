"""Move policy dispatcher."""

from __future__ import annotations

import chess

from app.engine import StockfishEngine
from app.models import MoveRequest
from app.policies import bad, best, grit, rebellion, skill
from app.policies.base import PolicyResult

__all__ = ["PolicyResult", "choose_move"]


def choose_move(
    engine: StockfishEngine,
    board: chess.Board,
    req: MoveRequest,
) -> PolicyResult:
    difficulty = req.difficulty
    if difficulty in ("grit", "pocket_sand"):
        return grit.choose(engine, board, req)
    if difficulty == "best":
        return best.choose(engine, board, req)
    if difficulty in ("skill", "elo"):
        return skill.choose(engine, board, req)
    if difficulty == "bad":
        return bad.choose(engine, board, req)
    if difficulty == "rebellion":
        return rebellion.choose(engine, board, req)
    raise ValueError(f"Unknown difficulty: {difficulty}")
