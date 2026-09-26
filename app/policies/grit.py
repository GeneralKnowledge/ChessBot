"""
Grit — pawn-heavy trickster personality.

Priority: coup → defend → free capture → bait/threat/punish → multipv + soft pawn bias.
Quiet positions go through MultiPV + soft bias — never hard-pick best pawn advance.
"""

from __future__ import annotations

import chess

from app.chess_utils import (
    hanging_loss_after,
    is_free_capture,
    mate_in_one_exists,
    move_is_pawn,
    piece_value,
    prefer_piece_boost,
    score_to_cp,
    static_exchange_approx,
    walks_into_mate,
)
from app.config import Settings, get_settings
from app.engine import EngineLine, StockfishEngine
from app.models import MoveRequest
from app.policies.base import PolicyResult

MAJOR_WIN_CP = 400


def _movetime(req: MoveRequest) -> int:
    if req.movetime_ms is not None:
        return req.movetime_ms
    return 60 if req.fast else 180


def _find_coup(
    engine: StockfishEngine,
    board: chess.Board,
    horizon: int,
    movetime: int,
) -> EngineLine | None:
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


def _needs_defense(engine: StockfishEngine, board: chess.Board, movetime: int) -> bool:
    if board.is_check():
        return True
    probe = board.copy(stack=False)
    probe.turn = not probe.turn
    if mate_in_one_exists(probe) is not None:
        return True

    lines = engine.analyse(board, movetime_ms=max(40, movetime // 2), multipv=1)
    if lines and lines[0].mate is not None and lines[0].mate < 0 and abs(lines[0].mate) <= 2:
        return True
    return False


def _best_defense(
    engine: StockfishEngine,
    board: chess.Board,
    movetime: int,
) -> PolicyResult | None:
    n = min(8, board.legal_moves.count())
    lines = engine.analyse(board, movetime_ms=movetime, multipv=max(1, n))
    if not lines:
        return None
    safe = [ln for ln in lines if not walks_into_mate(board, ln.move)]
    pool = safe or lines
    pick = pool[0]
    return PolicyResult(
        move=pick.move,
        reason="grit_defend",
        eval_cp=pick.score_cp,
        mate=pick.mate,
        pv=pick.pv,
    )


def _free_captures(board: chess.Board, threshold: int) -> list[chess.Move]:
    caps = [m for m in board.legal_moves if is_free_capture(board, m, threshold)]
    caps.sort(
        key=lambda m: (
            -static_exchange_approx(board, m),
            0 if move_is_pawn(board, m) else 1,
        )
    )
    return caps


def _capture_moves_on(board: chess.Board, square: chess.Square) -> list[chess.Move]:
    moves: list[chess.Move] = []
    for atk in board.attackers(board.turn, square):
        mv = chess.Move(atk, square)
        ap = board.piece_at(atk)
        if ap and ap.piece_type == chess.PAWN and chess.square_rank(square) in (0, 7):
            mv = chess.Move(atk, square, promotion=chess.QUEEN)
        if board.is_legal(mv):
            moves.append(mv)
    return moves


def _hanging_our_squares(board: chess.Board) -> list[chess.Square]:
    """Squares with our pieces that opponent (STM) can capture."""
    our = not board.turn
    out: list[chess.Square] = []
    for sq in chess.SQUARES:
        p = board.piece_at(sq)
        if p is None or p.color != our or p.piece_type == chess.KING:
            continue
        if board.attackers(board.turn, sq):
            out.append(sq)
    return out


def _eval_after_greedy_take(
    board: chess.Board,
    our_move: chess.Move,
    engine: StockfishEngine,
    movetime: int,
) -> tuple[bool, int, int]:
    """
    After our_move, if opponent takes a hanging piece of ours, evaluate our reply.

    Returns (success, hang_cp_offered, best_gain_cp_for_us).
    success = mate <= 2 or major material/eval win.
    """
    if not board.is_legal(our_move):
        return False, 0, 0

    board.push(our_move)
    try:
        hang_squares = _hanging_our_squares(board)
        if not hang_squares:
            return False, 0, 0

        # Prefer the most valuable hanging piece (the bait)
        hang_squares.sort(
            key=lambda sq: -piece_value(
                board.piece_at(sq).piece_type if board.piece_at(sq) else None
            )
        )
        top = board.piece_at(hang_squares[0])
        hang_cp = piece_value(top.piece_type if top else None)
        take_moves = _capture_moves_on(board, hang_squares[0])
        if not take_moves:
            return False, hang_cp, 0

        best_for_us = -10_000
        success = False
        for take in take_moves[:8]:
            board.push(take)
            try:
                if mate_in_one_exists(board) is not None:
                    success = True
                    best_for_us = max(best_for_us, 10_000)
                    continue
                lines = engine.analyse(board, movetime_ms=max(30, movetime // 3), multipv=1)
                if not lines:
                    continue
                ln = lines[0]
                if ln.mate is not None and 0 < ln.mate <= 2:
                    success = True
                    best_for_us = max(best_for_us, 10_000)
                else:
                    cp = score_to_cp(ln.mate, ln.score_cp)
                    best_for_us = max(best_for_us, cp)
                    if cp >= MAJOR_WIN_CP:
                        success = True
            finally:
                board.pop()
        return success, hang_cp, best_for_us
    finally:
        board.pop()


def _find_bait_threat_punish(
    engine: StockfishEngine,
    board: chess.Board,
    movetime: int,
    multipv: int,
) -> PolicyResult | None:
    lines = engine.analyse(board, movetime_ms=movetime, multipv=multipv)
    cand: dict[str, chess.Move] = {ln.move.uci(): ln.move for ln in lines}
    for m in board.legal_moves:
        if board.is_capture(m) or board.gives_check(m):
            cand[m.uci()] = m

    line_by = {ln.move.uci(): ln for ln in lines}
    baits: list[tuple[int, chess.Move]] = []
    punishes: list[tuple[int, chess.Move]] = []
    threats: list[tuple[int, chess.Move]] = []

    for uci, move in cand.items():
        if walks_into_mate(board, move):
            continue

        # Threat: after our move, opponent faces mate-in-1/2 (their eval mate < 0)
        board.push(move)
        try:
            short = engine.analyse(board, movetime_ms=max(30, movetime // 3), multipv=1)
            if short and short[0].mate is not None and short[0].mate < 0 and abs(short[0].mate) <= 2:
                threats.append((abs(short[0].mate), move))
        finally:
            board.pop()

        success, hang_cp, gain = _eval_after_greedy_take(board, move, engine, movetime)
        if not success:
            continue
        if hang_cp >= 300:
            baits.append((gain, move))
        else:
            # Punish greed on hanging pawns / smaller hangs, or any takeable piece
            punishes.append((gain, move))

    for pool, reason in (
        (baits, "grit_bait"),
        (threats, "grit_threat"),
        (punishes, "grit_punish"),
    ):
        if not pool:
            continue
        pool.sort(key=lambda t: -t[0])
        _gain, move = pool[0]
        ln = line_by.get(move.uci())
        return PolicyResult(
            move=move,
            reason=reason,
            eval_cp=ln.score_cp if ln else None,
            mate=ln.mate if ln else None,
            pv=ln.pv if ln else [move],
            metadata={"tactic_gain_cp": _gain},
        )
    return None


def _anti_hang_ok(board: chess.Board, move: chess.Move, settings: Settings) -> bool:
    is_quiet = not board.is_capture(move) and not board.gives_check(move)
    loss = hanging_loss_after(board, move)
    if is_quiet:
        if loss >= settings.grit_hang_pawn_cp:
            return False
        return True
    if loss >= settings.grit_hang_minor_cp and not is_free_capture(
        board, move, settings.grit_free_capture_cp
    ):
        return loss < 500
    return True


def _soft_bias_pick(
    engine: StockfishEngine,
    board: chess.Board,
    req: MoveRequest,
    movetime: int,
    settings: Settings,
) -> PolicyResult:
    n_legal = board.legal_moves.count()
    multipv = req.multipv or min(settings.multipv, max(3, n_legal))
    lines = engine.analyse(board, movetime_ms=movetime, multipv=multipv)
    if not lines:
        return PolicyResult(move=next(iter(board.legal_moves)), reason="grit_fallback")

    best = lines[0]
    best_cp = score_to_cp(best.mate, best.score_cp)

    if best.mate is not None and best.mate > 0:
        return PolicyResult(
            move=best.move,
            reason="grit_obvious",
            eval_cp=best.score_cp,
            mate=best.mate,
            pv=best.pv,
        )

    gap = 0
    if len(lines) >= 2:
        gap = best_cp - score_to_cp(lines[1].mate, lines[1].score_cp)

    if gap >= settings.grit_obvious_gap_cp:
        return PolicyResult(
            move=best.move,
            reason="grit_obvious",
            eval_cp=best.score_cp,
            mate=best.mate,
            pv=best.pv,
            metadata={"gap_cp": gap},
        )

    bias = settings.grit_pawn_bias
    scored: list[tuple[float, EngineLine]] = []
    for ln in lines:
        if walks_into_mate(board, ln.move):
            continue
        if not _anti_hang_ok(board, ln.move, settings):
            continue
        cp = score_to_cp(ln.mate, ln.score_cp)
        if cp < best_cp - 350:
            continue
        bonus = float(bias) if move_is_pawn(board, ln.move) else 0.0
        bonus += prefer_piece_boost(board, ln.move, req.prefer_piece)
        scored.append((cp + bonus, ln))

    if not scored:
        for ln in lines:
            if walks_into_mate(board, ln.move):
                continue
            cp = score_to_cp(ln.mate, ln.score_cp)
            bonus = float(bias) if move_is_pawn(board, ln.move) else 0.0
            scored.append((cp + bonus, ln))

    if not scored:
        return PolicyResult(
            move=best.move,
            reason="grit_obvious",
            eval_cp=best.score_cp,
            mate=best.mate,
            pv=best.pv,
        )

    scored.sort(key=lambda t: -t[0])
    pick = scored[0][1]
    reason = "grit_pawn" if move_is_pawn(board, pick.move) else "grit_quiet"
    return PolicyResult(
        move=pick.move,
        reason=reason,
        eval_cp=pick.score_cp,
        mate=pick.mate,
        pv=pick.pv,
        metadata={
            "pawn_bias": bias,
            "biased_score": scored[0][0],
            "best_cp": best_cp,
            "gap_cp": gap,
        },
    )


def choose(engine: StockfishEngine, board: chess.Board, req: MoveRequest) -> PolicyResult:
    settings = get_settings()
    movetime = _movetime(req)
    horizon = req.win_horizon
    multipv = req.multipv or settings.multipv

    # 1. Mate coups
    coup = _find_coup(engine, board, horizon, movetime)
    if coup is not None:
        return PolicyResult(
            move=coup.move,
            reason="grit_coup",
            eval_cp=coup.score_cp,
            mate=coup.mate,
            pv=coup.pv,
        )

    # 2. Defend if mating attack
    if _needs_defense(engine, board, movetime):
        defense = _best_defense(engine, board, movetime)
        if defense is not None and not walks_into_mate(board, defense.move):
            return defense
        safe = [m for m in board.legal_moves if not walks_into_mate(board, m)]
        if safe:
            lines = engine.analyse(board, movetime_ms=movetime, multipv=min(8, len(safe)))
            for ln in lines:
                if ln.move in safe:
                    return PolicyResult(
                        move=ln.move,
                        reason="grit_defend",
                        eval_cp=ln.score_cp,
                        mate=ln.mate,
                        pv=ln.pv,
                    )
            return PolicyResult(move=safe[0], reason="grit_defend")

    # 3. Free captures
    for move in _free_captures(board, settings.grit_free_capture_cp):
        if walks_into_mate(board, move):
            continue
        return PolicyResult(move=move, reason="grit_capture")

    # 4. Bait / threat / punish
    tactic = _find_bait_threat_punish(engine, board, movetime, multipv)
    if tactic is not None:
        return tactic

    # 5. MultiPV + soft pawn bias
    return _soft_bias_pick(engine, board, req, movetime, settings)


def is_poison_bait(
    board: chess.Board,
    move: chess.Move,
    engine: StockfishEngine,
    movetime: int = 80,
) -> bool:
    success, hang_cp, _ = _eval_after_greedy_take(board, move, engine, movetime)
    return success and hang_cp >= 300
