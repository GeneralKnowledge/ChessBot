"""Rebellion — pawn-first, free captures, take forced mates within horizon."""

from __future__ import annotations

import chess

from app.chess_utils import (
    is_free_capture,
    mate_in_one_exists,
    move_is_pawn,
    prefer_piece_boost,
)
from app.engine import EngineLine, StockfishEngine
from app.models import MoveRequest
from app.policies.base import PolicyResult


def _forced_mate(engine: StockfishEngine, board: chess.Board, horizon: int, movetime: int):
    m1 = mate_in_one_exists(board)
    if m1 is not None:
        return EngineLine(move=m1, score_cp=None, mate=1, pv=[m1], multipv_index=1)
    lines = engine.analyse(board, movetime_ms=movetime, multipv=1)
    if not lines:
        return None
    line = lines[0]
    if line.mate is not None and 0 < line.mate <= horizon:
        return line
    return None


def choose(engine: StockfishEngine, board: chess.Board, req: MoveRequest) -> PolicyResult:
    movetime = req.movetime_ms or (80 if req.fast else 150)
    horizon = req.win_horizon

    coup = _forced_mate(engine, board, horizon, movetime)
    if coup is not None:
        return PolicyResult(
            move=coup.move,
            reason="rebellion_coup",
            mate=coup.mate,
            eval_cp=coup.score_cp,
            pv=coup.pv,
        )

    free = [
        m
        for m in board.legal_moves
        if is_free_capture(board, m, threshold_cp=100)
    ]
    if free:
        # Prefer pawn captures, then prefer_piece
        free.sort(
            key=lambda m: (
                0 if move_is_pawn(board, m) else 1,
                -prefer_piece_boost(board, m, req.prefer_piece),
            )
        )
        return PolicyResult(move=free[0], reason="rebellion_capture")

    pawns = [m for m in board.legal_moves if move_is_pawn(board, m)]
    if pawns:
        if req.prefer_piece:
            boosted = [m for m in pawns if prefer_piece_boost(board, m, req.prefer_piece)]
            if boosted:
                pawns = boosted
        # Prefer advances that aren't obviously hanging — light filter
        return PolicyResult(move=pawns[0], reason="rebellion_pawn")

    lines = engine.analyse(board, movetime_ms=movetime, multipv=3)
    if lines:
        return PolicyResult(
            move=lines[0].move,
            reason="rebellion_fallback",
            eval_cp=lines[0].score_cp,
            mate=lines[0].mate,
            pv=lines[0].pv,
        )
    return PolicyResult(move=next(iter(board.legal_moves)), reason="rebellion_fallback")
