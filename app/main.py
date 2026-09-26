"""FastAPI application — Stockfish chess API."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException

from app import __version__
from app.chess_utils import material_balance, normalize_fen
from app.config import get_settings
from app.engine import EngineError, get_engine
from app.models import (
    AnalyzeRequest,
    AnalyzeResponse,
    HealthResponse,
    LineInfo,
    MoveRequest,
    MoveResponse,
    ScoreInfo,
)
from app.policies import choose_move

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    engine = get_engine()
    engine.start()
    logger.info("ChessBot %s ready", __version__)
    yield
    engine.close()


app = FastAPI(
    title="ChessBot",
    description="Stateless Stockfish wrapper with move personalities (Grit and friends).",
    version=__version__,
    lifespan=lifespan,
)


def _score_info(mate: int | None, score_cp: int | None) -> ScoreInfo | None:
    if mate is not None:
        return ScoreInfo(unit="mate", value=mate)
    if score_cp is not None:
        return ScoreInfo(unit="cp", value=score_cp)
    return None


def _resign_draw_guess(
    board: chess.Board,
    eval_cp: int | None,
    mate: int | None,
    move_number: int | None,
) -> tuple[bool | None, bool | None]:
    """Rough stateless guesses — keep simple."""
    mn = move_number or board.fullmove_number
    if mate is not None and mate < 0 and abs(mate) <= 3 and mn >= 8:
        return True, False
    if eval_cp is not None and eval_cp <= -600 and mn >= 12:
        return True, False
    if eval_cp is not None and abs(eval_cp) < 30 and mn >= 40:
        bal = abs(material_balance(board, board.turn))
        if bal < 100:
            return False, True
    return None, None


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    settings = get_settings()
    engine = get_engine()
    ready = engine.ping()
    return HealthResponse(
        status="ok" if ready else "error",
        engine="stockfish",
        stockfish_path=settings.stockfish_path,
        ready=ready,
    )


@app.post("/move", response_model=MoveResponse)
def move(req: MoveRequest) -> MoveResponse:
    try:
        board = normalize_fen(req.fen, req.move_number)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if board.is_game_over():
        raise HTTPException(status_code=400, detail="Position is already game over")

    engine = get_engine()
    try:
        result = choose_move(engine, board, req)
    except EngineError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    san = None
    fen_after = None
    try:
        san = board.san(result.move)
        board.push(result.move)
        fen_after = board.fen()
        board.pop()
    except Exception:  # noqa: BLE001
        logger.exception("SAN encode failed")

    resign, draw = _resign_draw_guess(
        board, result.eval_cp, result.mate, req.move_number
    )
    pv_uci = [m.uci() for m in result.pv] if result.pv else None

    return MoveResponse(
        move=result.move.uci(),
        san=san,
        reason=result.reason,
        difficulty="grit" if req.difficulty == "pocket_sand" else req.difficulty,
        fen=board.fen(),
        fen_after=fen_after,
        eval=_score_info(result.mate, result.eval_cp),
        pv=pv_uci,
        resign_guess=resign,
        draw_guess=draw,
        metadata=result.metadata,
    )


@app.post("/analyze", response_model=AnalyzeResponse)
def analyze(req: AnalyzeRequest) -> AnalyzeResponse:
    settings = get_settings()
    try:
        board = normalize_fen(req.fen)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    engine = get_engine()
    movetime = req.movetime_ms or settings.analyze_movetime_ms
    try:
        lines = engine.analyse(
            board,
            movetime_ms=movetime,
            depth=req.depth,
            multipv=req.multipv,
        )
    except EngineError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    out: list[LineInfo] = []
    for ln in lines:
        try:
            san = board.san(ln.move)
        except Exception:  # noqa: BLE001
            san = None
        score = _score_info(ln.mate, ln.score_cp) or ScoreInfo(unit="cp", value=0)
        out.append(
            LineInfo(
                move=ln.move.uci(),
                san=san,
                score=score,
                pv=[m.uci() for m in ln.pv],
            )
        )

    return AnalyzeResponse(
        fen=board.fen(),
        best_move=out[0].move if out else None,
        lines=out,
    )

