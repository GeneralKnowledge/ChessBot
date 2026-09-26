"""Grit personality tests — coup, defense, bait, free capture."""

from __future__ import annotations

import chess

from app.chess_utils import is_free_capture, mate_in_one_exists, walks_into_mate
from app.models import MoveRequest
from app.policies import grit
from app.policies.grit import is_poison_bait

START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


def test_mate_in_one_takes_mate(engine):
    board = chess.Board("6k1/5ppp/8/8/8/8/8/4Q1K1 w - - 0 1")
    assert mate_in_one_exists(board) is not None
    req = MoveRequest(fen=board.fen(), difficulty="grit", win_horizon=5, fast=True)
    result = grit.choose(engine, board, req)
    assert result.reason == "grit_coup"
    board.push(result.move)
    assert board.is_checkmate()


def test_refuses_pawn_into_mate(engine):
    # Bishop+queen battery on the long diagonal; g2-g3/g4 open mate.
    board = chess.Board("6k1/5ppp/8/8/4b3/4q3/5PPP/6K1 w - - 0 1")
    pawn_moves = [
        m
        for m in board.legal_moves
        if board.piece_at(m.from_square)
        and board.piece_at(m.from_square).piece_type == chess.PAWN
    ]
    suicidal = [m for m in pawn_moves if walks_into_mate(board, m)]
    assert suicidal, "expected at least one pawn push into mate"

    req = MoveRequest(
        fen=board.fen(),
        difficulty="grit",
        win_horizon=5,
        fast=True,
        movetime_ms=100,
    )
    result = grit.choose(engine, board, req)
    assert result.reason in {
        "grit_defend",
        "grit_obvious",
        "grit_quiet",
        "grit_coup",
        "grit_capture",
        "grit_pawn",
    }
    assert not walks_into_mate(board, result.move)
    assert result.move.uci() not in {m.uci() for m in suicidal}


def test_free_capture_taken(engine):
    board = chess.Board("4k3/8/8/8/3q4/4P3/8/4K3 w - - 0 1")
    take = chess.Move.from_uci("e3d4")
    assert take in board.legal_moves
    assert is_free_capture(board, take, threshold_cp=100)

    req = MoveRequest(
        fen=board.fen(),
        difficulty="grit",
        win_horizon=5,
        fast=True,
        movetime_ms=80,
    )
    result = grit.choose(engine, board, req)
    assert result.reason in {"grit_capture", "grit_coup", "grit_obvious"}
    assert board.is_capture(result.move)
    assert result.move.to_square == chess.D4


def test_poison_bait_detected(engine):
    # 1.Qe8 (queen en prise) 2...Rxe8 3.Rxe8#
    board = chess.Board("5r1k/6pp/8/8/8/8/4Q3/4R1K1 w - - 0 1")
    sac = chess.Move.from_uci("e2e8")
    assert sac in board.legal_moves

    board.push(sac)
    take = chess.Move.from_uci("f8e8")
    assert take in board.legal_moves
    board.push(take)
    m1 = mate_in_one_exists(board)
    assert m1 is not None
    board.push(m1)
    assert board.is_checkmate()
    board.pop()
    board.pop()
    board.pop()

    assert is_poison_bait(board, sac, engine, movetime=80)


def test_move_endpoint_grit(client):
    r = client.post(
        "/move",
        json={"fen": START_FEN, "difficulty": "grit", "fast": True, "movetime_ms": 80},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["move"]
    assert data["difficulty"] == "grit"
    assert data["reason"].startswith("grit_")


def test_analyze_endpoint(client):
    r = client.post(
        "/analyze",
        json={"fen": START_FEN, "movetime_ms": 100, "multipv": 2},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["best_move"]
    assert len(data["lines"]) >= 1


def test_pocket_sand_alias(client):
    r = client.post(
        "/move",
        json={
            "fen": "6k1/5ppp/8/8/8/8/8/4Q1K1 w - - 0 1",
            "difficulty": "pocket_sand",
            "fast": True,
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data["difficulty"] == "grit"
    assert data["reason"] == "grit_coup"
