"""Shared policy result type."""

from __future__ import annotations

from dataclasses import dataclass, field

import chess


@dataclass
class PolicyResult:
    move: chess.Move
    reason: str
    eval_cp: int | None = None
    mate: int | None = None
    pv: list[chess.Move] = field(default_factory=list)
    metadata: dict[str, object] = field(default_factory=dict)
