"""Request / response models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Difficulty = Literal[
    "best",
    "skill",
    "elo",
    "bad",
    "rebellion",
    "grit",
    "pocket_sand",
]

PreferPiece = Literal[
    "pawn",
    "knight",
    "bishop",
    "rook",
    "queen",
    "king",
]


class MoveRequest(BaseModel):
    fen: str = Field(..., description="Position FEN (full or board-only + defaults)")
    difficulty: Difficulty = "grit"
    prefer_piece: PreferPiece | None = None
    win_horizon: int = Field(5, ge=1, le=10)
    skill_level: int | None = Field(None, ge=0, le=20)
    elo: int | None = Field(None, ge=1320, le=3190)
    movetime_ms: int | None = Field(None, ge=20, le=10_000)
    multipv: int | None = Field(None, ge=1, le=20)
    fast: bool = Field(False, description="Lighter search (for probes / demos)")
    move_number: int | None = Field(None, description="Optional full-move number override")


class ScoreInfo(BaseModel):
    unit: Literal["cp", "mate"]
    value: int
    # Positive is good for the side to move


class MoveResponse(BaseModel):
    move: str
    san: str | None = None
    reason: str
    difficulty: str
    fen: str
    fen_after: str | None = None
    eval: ScoreInfo | None = None
    pv: list[str] | None = None
    resign_guess: bool | None = None
    draw_guess: bool | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class AnalyzeRequest(BaseModel):
    fen: str
    movetime_ms: int | None = Field(None, ge=50, le=30_000)
    multipv: int = Field(3, ge=1, le=10)
    depth: int | None = Field(None, ge=1, le=40)


class LineInfo(BaseModel):
    move: str
    san: str | None = None
    score: ScoreInfo
    pv: list[str]


class AnalyzeResponse(BaseModel):
    fen: str
    best_move: str | None
    lines: list[LineInfo]


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded", "error"]
    engine: str
    stockfish_path: str
    ready: bool
