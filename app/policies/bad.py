"""Bad / among-worst multipv moves."""

from __future__ import annotations

import chess

from app.chess_utils import prefer_piece_boost
from app.engine import StockfishEngine
from app.models import MoveRequest
from app.policies.base import PolicyResult


def choose(engine: StockfishEngine, board: chess.Board, req: MoveRequest) -> PolicyResult:
    movetime = req.movetime_ms or (80 if req.fast else 150)
    multipv = req.multipv or 8
    lines = engine.analyse(board, movetime_ms=movetime, multipv=multipv)
    legal = list(board.legal_moves)
    if not legal:
        raise ValueError("No legal moves")

    if not lines:
        move = legal[0]
        return PolicyResult(move=move, reason="bad_fallback")

    # Score ascending (worst first); mates against us first
    def sort_key(line):  # noqa: ANN001
        if line.mate is not None:
            if line.mate < 0:
                return (-10_000 + line.mate, 0)
            return (10_000 - line.mate, 0)
        return (line.score_cp if line.score_cp is not None else 0, 0)

    ranked = sorted(lines, key=sort_key)
    # Prefer among the bottom third
    cutoff = max(1, len(ranked) // 3)
    candidates = ranked[:cutoff]

    prefer = req.prefer_piece
    if prefer:
        boosted = [
            c
            for c in candidates
            if prefer_piece_boost(board, c.move, prefer) > 0
        ]
        if boosted:
            candidates = boosted

    pick = candidates[0]
    return PolicyResult(
        move=pick.move,
        reason="bad",
        eval_cp=pick.score_cp,
        mate=pick.mate,
        pv=pick.pv,
        metadata={"multipv_index": pick.multipv_index, "prefer_piece": prefer},
    )
