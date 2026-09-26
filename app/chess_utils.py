"""Chess helpers: FEN normalize, material, SEE-ish, hang detection."""

from __future__ import annotations

import chess

PIECE_VALUES = {
    chess.PAWN: 100,
    chess.KNIGHT: 320,
    chess.BISHOP: 330,
    chess.ROOK: 500,
    chess.QUEEN: 900,
    chess.KING: 20_000,
}

PIECE_NAME = {
    chess.PAWN: "pawn",
    chess.KNIGHT: "knight",
    chess.BISHOP: "bishop",
    chess.ROOK: "rook",
    chess.QUEEN: "queen",
    chess.KING: "king",
}

NAME_TO_PIECE = {v: k for k, v in PIECE_NAME.items()}


def normalize_fen(fen: str, move_number: int | None = None) -> chess.Board:
    fen = fen.strip()
    parts = fen.split()
    if len(parts) == 1:
        fen = f"{parts[0]} w - - 0 1"
    elif len(parts) == 2:
        fen = f"{parts[0]} {parts[1]} - - 0 1"
    board = chess.Board(fen)
    if move_number is not None:
        board.fullmove_number = move_number
    if not board.is_valid():
        # Still allow legal positions that fail status checks lightly
        status = board.status()
        if status & chess.STATUS_NO_WHITE_KING or status & chess.STATUS_NO_BLACK_KING:
            raise ValueError(f"Invalid FEN: {fen}")
    return board


def piece_value(piece_type: chess.PieceType | None) -> int:
    if piece_type is None:
        return 0
    return PIECE_VALUES.get(piece_type, 0)


def material_balance(board: chess.Board, color: chess.Color) -> int:
    total = 0
    for pt, val in PIECE_VALUES.items():
        if pt == chess.KING:
            continue
        total += len(board.pieces(pt, color)) * val
        total -= len(board.pieces(pt, not color)) * val
    return total


def move_is_pawn(board: chess.Board, move: chess.Move) -> bool:
    piece = board.piece_at(move.from_square)
    return piece is not None and piece.piece_type == chess.PAWN


def move_piece_type(board: chess.Board, move: chess.Move) -> chess.PieceType | None:
    piece = board.piece_at(move.from_square)
    return piece.piece_type if piece else None


def capture_value(board: chess.Board, move: chess.Move) -> int:
    if board.is_en_passant(move):
        return PIECE_VALUES[chess.PAWN]
    captured = board.piece_at(move.to_square)
    return piece_value(captured.piece_type if captured else None)


def static_exchange_approx(board: chess.Board, move: chess.Move) -> int:
    """
    Cheap SEE approximation: capture gain minus cheapest immediate recapture,
    else just capture value for non-captures returns 0.
    """
    if not board.is_capture(move) and not board.is_en_passant(move):
        return 0
    gain = capture_value(board, move)
    mover = board.piece_at(move.from_square)
    if mover is None:
        return gain
    # Recapture availability
    attackers = board.attackers(not board.turn, move.to_square)
    if not attackers:
        return gain
    # Cheapest attacker value
    cheapest = min(
        piece_value(board.piece_at(sq).piece_type)  # type: ignore[union-attr]
        for sq in attackers
        if board.piece_at(sq) is not None
    )
    # If we leave a more valuable piece hanging on the square after capture
    # (ignoring defenders for speed), subtract.
    our_left = piece_value(mover.piece_type)
    # Promotions: treat as queen for hanging estimate
    if move.promotion:
        our_left = piece_value(move.promotion)
    return gain - min(our_left, cheapest)


def is_free_capture(board: chess.Board, move: chess.Move, threshold_cp: int = 100) -> bool:
    if not (board.is_capture(move) or board.is_en_passant(move)):
        return False
    return static_exchange_approx(board, move) >= threshold_cp


def hanging_loss_after(board: chess.Board, move: chess.Move) -> int:
    """
    Estimate max material we leave hanging after `move` (quiet or otherwise).
    Looks at our pieces that opponent can capture with positive SEE next turn.
    """
    if not board.is_legal(move):
        return 0
    board.push(move)
    try:
        worst = 0
        opp = board.turn
        our = not opp
        for sq in chess.SQUARES:
            piece = board.piece_at(sq)
            if piece is None or piece.color != our:
                continue
            if piece.piece_type == chess.KING:
                continue
            attackers = board.attackers(opp, sq)
            if not attackers:
                continue
            # Can opponent capture this piece profitably?
            for atk in attackers:
                cap = chess.Move(atk, sq)
                # Handle promotions for pawns to last rank
                atk_piece = board.piece_at(atk)
                if atk_piece and atk_piece.piece_type == chess.PAWN:
                    to_rank = chess.square_rank(sq)
                    if to_rank in (0, 7) and cap.promotion is None:
                        cap.promotion = chess.QUEEN
                if not board.is_legal(cap):
                    continue
                see = static_exchange_approx(board, cap)
                if see >= 80:
                    worst = max(worst, piece_value(piece.piece_type))
                    break
        return worst
    finally:
        board.pop()


def gives_check(board: chess.Board, move: chess.Move) -> bool:
    board.push(move)
    try:
        return board.is_check()
    finally:
        board.pop()


def opponent_in_checkmate_after(board: chess.Board, move: chess.Move) -> bool:
    board.push(move)
    try:
        return board.is_checkmate()
    finally:
        board.pop()


def mate_in_one_exists(board: chess.Board) -> chess.Move | None:
    for move in board.legal_moves:
        if opponent_in_checkmate_after(board, move):
            return move
    return None


def is_under_mate_threat(board: chess.Board, ply: int = 2) -> bool:
    """True if opponent has forced mate within `ply` half-moves assuming we pass...

    Practical check:
    - ply=1: opponent has mate-in-1 now (we're to move — means we are already mated? no)
    - We are STM. Threat of mate-in-1 means: after every legal move? No —
      "under mate-in-1" means opponent threatens mate next move if we don't address it.
      So: for current position, if we make a null... we can't. Instead check whether
      there exists at least one opponent reply that is mate if we play a useless move —
      simpler: scan if ANY of our quiet non-defending moves leave a mate-in-1 for them,
      OR check current checks.

    Spec: "if under mate-in-1/2, stop pawn-pushing into mate"
    Implementation: after our candidate move, does opponent have mate-in-1?
    For threat detection before choosing: opponent currently threatens mate-in-1
    if there exists a move we must answer — i.e. for each legal "ignore" ... 

    We'll use: board has mate threat if for the side to move, failure to address
    allows mate. Detect by: any legal move for opponent that is mate-in-1 after
    we play a null isn't possible. Alternative: analyse with engine.

    For defend rule we use engine mate scores + local checks:
    - If opponent has mate-in-1 available after our move → our move walked into mate
    - Pre-move: if we are in check, or if ALL non-defensive moves lose to mate-in-1
    """
    # Threat of mate-in-1: exists a legal move M such that after EVERY reply? No.
    # "Threatens mate in 1" = opponent (not STM) would mate if it were their turn.
    # Create a mirror by assuming null move only if not in check.
    if board.is_check():
        return True
    # Probe: if we pass the turn illegally via board.turn flip for threat scan
    probe = board.copy(stack=False)
    probe.turn = not probe.turn
    if mate_in_one_exists(probe) is not None:
        return True
    if ply >= 2:
        # Mate-in-2 threat: opponent has a check that forces mate-in-1 after our reply
        # Keep cheap: any checking move by flipped side that leaves us with only mating replies
        for move in list(probe.legal_moves)[:40]:
            if not gives_check(probe, move):
                continue
            probe.push(move)
            # Now original side to move — if all replies still allow mate-in-1 for opp, strong threat
            replies = list(probe.legal_moves)
            if not replies:
                probe.pop()
                if probe.is_checkmate():
                    return True
                continue
            forced = True
            for reply in replies[:30]:
                probe.push(reply)
                still = mate_in_one_exists(probe) is not None
                probe.pop()
                if not still:
                    forced = False
                    break
            probe.pop()
            if forced:
                return True
    return False


def walks_into_mate(board: chess.Board, move: chess.Move) -> bool:
    """True if after `move`, opponent has mate-in-1."""
    if not board.is_legal(move):
        return True
    board.push(move)
    try:
        return mate_in_one_exists(board) is not None
    finally:
        board.pop()


def prefer_piece_boost(board: chess.Board, move: chess.Move, prefer: str | None) -> int:
    if not prefer:
        return 0
    pt = NAME_TO_PIECE.get(prefer)
    if pt is None:
        return 0
    if move_piece_type(board, move) == pt:
        return 40
    return 0


def score_to_cp(mate: int | None, score_cp: int | None) -> int:
    if mate is not None:
        if mate > 0:
            return 10_000 - mate * 10
        return -10_000 - mate * 10
    return score_cp if score_cp is not None else 0
