"""Best move — full-strength Stockfish."""

from __future__ import annotations

import chess

from app.engine import StockfishEngine
from app.models import MoveRequest
from app.policies.base import PolicyResult


def choose(engine: StockfishEngine, board: chess.Board, req: MoveRequest) -> PolicyResult:
    movetime = req.movetime_ms or (80 if req.fast else None)
    lines = engine.analyse(board, movetime_ms=movetime, multipv=1)
    if not lines:
        move = next(iter(board.legal_moves))
        return PolicyResult(move=move, reason="best_fallback")
    line = lines[0]
    return PolicyResult(
        move=line.move,
        reason="best",
        eval_cp=line.score_cp,
        mate=line.mate,
        pv=line.pv,
        metadata={"skill": 20},
    )
