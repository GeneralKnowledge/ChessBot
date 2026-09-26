"""Runtime configuration."""

from __future__ import annotations

import os
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    stockfish_path: str = os.environ.get("STOCKFISH_PATH", "/usr/games/stockfish")
    default_movetime_ms: int = 200
    analyze_movetime_ms: int = 500
    multipv: int = 8
    grit_pawn_bias: int = int(os.environ.get("GRIT_PAWN_BIAS", "65"))
    grit_obvious_gap_cp: int = 250
    grit_free_capture_cp: int = 100
    grit_hang_minor_cp: int = 300
    grit_hang_pawn_cp: int = 80
    elo_floor: int = 1320


@lru_cache
def get_settings() -> Settings:
    return Settings()
