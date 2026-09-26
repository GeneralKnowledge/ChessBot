"""Thread-safe Stockfish UCI engine wrapper with restart on desync."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any

import chess
import chess.engine

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)


@dataclass
class EngineLine:
    move: chess.Move
    score_cp: int | None  # from side-to-move POV; mate encoded separately
    mate: int | None  # positive = STM mates in N
    pv: list[chess.Move]
    multipv_index: int


class EngineError(RuntimeError):
    pass


class StockfishEngine:
    """Serialize all UCI access; restart the process after hard failures."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._lock = threading.RLock()
        self._engine: chess.engine.SimpleEngine | None = None
        self._path = self.settings.stockfish_path

    def start(self) -> None:
        with self._lock:
            self._open()

    def close(self) -> None:
        with self._lock:
            self._close_unlocked()

    def _close_unlocked(self) -> None:
        if self._engine is not None:
            try:
                self._engine.quit()
            except Exception:  # noqa: BLE001
                logger.exception("Error quitting Stockfish")
            self._engine = None

    def _open(self) -> chess.engine.SimpleEngine:
        if self._engine is not None:
            return self._engine
        try:
            self._engine = chess.engine.SimpleEngine.popen_uci(self._path)
            self._engine.configure({"Threads": 1, "Hash": 64})
            logger.info("Started Stockfish at %s", self._path)
            return self._engine
        except Exception as exc:  # noqa: BLE001
            self._engine = None
            raise EngineError(f"Failed to start Stockfish at {self._path}: {exc}") from exc

    def restart(self) -> None:
        with self._lock:
            logger.warning("Restarting Stockfish")
            self._close_unlocked()
            self._open()

    def ping(self) -> bool:
        with self._lock:
            try:
                engine = self._open()
                # Lightweight analyse to confirm responsiveness
                board = chess.Board()
                engine.analyse(board, chess.engine.Limit(nodes=1))
                return True
            except Exception:  # noqa: BLE001
                logger.exception("Engine ping failed")
                try:
                    self._close_unlocked()
                    self._open()
                    return True
                except Exception:  # noqa: BLE001
                    return False

    def _run(self, fn: Any, *args: Any, **kwargs: Any) -> Any:
        with self._lock:
            try:
                engine = self._open()
                return fn(engine, *args, **kwargs)
            except (chess.engine.EngineError, chess.engine.EngineTerminatedError) as exc:
                logger.warning("UCI/desync error (%s); restarting", exc)
                try:
                    self._close_unlocked()
                    engine = self._open()
                    return fn(engine, *args, **kwargs)
                except Exception as retry_exc:  # noqa: BLE001
                    raise EngineError(f"Engine failed after restart: {retry_exc}") from retry_exc
            except Exception as exc:  # noqa: BLE001
                logger.exception("Unexpected engine failure")
                try:
                    self._close_unlocked()
                    engine = self._open()
                    return fn(engine, *args, **kwargs)
                except Exception as retry_exc:  # noqa: BLE001
                    raise EngineError(str(retry_exc)) from retry_exc

    def configure(self, options: dict[str, Any]) -> None:
        def _cfg(engine: chess.engine.SimpleEngine) -> None:
            engine.configure(options)

        self._run(_cfg)

    def reset_strength(self) -> None:
        """Restore full strength (Skill 20, no limit)."""
        self.configure(
            {
                "Skill Level": 20,
                "UCI_LimitStrength": False,
            }
        )

    def analyse(
        self,
        board: chess.Board,
        *,
        movetime_ms: int | None = None,
        depth: int | None = None,
        multipv: int = 1,
        nodes: int | None = None,
    ) -> list[EngineLine]:
        limit_kwargs: dict[str, Any] = {}
        if nodes is not None:
            limit_kwargs["nodes"] = nodes
        elif depth is not None:
            limit_kwargs["depth"] = depth
        else:
            limit_kwargs["time"] = (movetime_ms or self.settings.default_movetime_ms) / 1000.0
        limit = chess.engine.Limit(**limit_kwargs)

        def _analyse(engine: chess.engine.SimpleEngine) -> list[EngineLine]:
            # MultiPV is managed by python-chess via analyse(..., multipv=);
            # only configure strength options here.
            engine.configure({"Skill Level": 20, "UCI_LimitStrength": False})
            raw = engine.analyse(board, limit, multipv=multipv)
            if isinstance(raw, dict):
                infos: list[chess.engine.InfoDict] = [raw]
            else:
                infos = list(raw)
            lines: list[EngineLine] = []
            for idx, info in enumerate(infos):
                pv = list(info.get("pv") or [])
                if not pv:
                    continue
                score = info.get("score")
                mate: int | None = None
                score_cp: int | None = None
                if score is not None:
                    pov = score.pov(board.turn)
                    if pov.is_mate():
                        mate = pov.mate()
                    else:
                        score_cp = pov.score(mate_score=10_000)
                lines.append(
                    EngineLine(
                        move=pv[0],
                        score_cp=score_cp,
                        mate=mate,
                        pv=pv,
                        multipv_index=idx + 1,
                    )
                )
            return lines

        return self._run(_analyse)

    def play(
        self,
        board: chess.Board,
        *,
        movetime_ms: int | None = None,
        depth: int | None = None,
        skill_level: int | None = None,
        elo: int | None = None,
        limit_strength: bool = False,
    ) -> chess.Move:
        limit_kwargs: dict[str, Any] = {}
        if depth is not None:
            limit_kwargs["depth"] = depth
        else:
            limit_kwargs["time"] = (movetime_ms or self.settings.default_movetime_ms) / 1000.0
        limit = chess.engine.Limit(**limit_kwargs)

        def _play(engine: chess.engine.SimpleEngine) -> chess.Move:
            opts: dict[str, Any] = {}
            if limit_strength and elo is not None:
                opts["UCI_LimitStrength"] = True
                opts["UCI_Elo"] = max(elo, self.settings.elo_floor)
            elif skill_level is not None:
                opts["UCI_LimitStrength"] = False
                opts["Skill Level"] = skill_level
            else:
                opts["UCI_LimitStrength"] = False
                opts["Skill Level"] = 20
            if opts:
                engine.configure(opts)
            result = engine.play(board, limit)
            if result.move is None:
                raise EngineError("Stockfish returned no move")
            return result.move

        return self._run(_play)


# Process-wide singleton
_engine: StockfishEngine | None = None
_engine_lock = threading.Lock()


def get_engine() -> StockfishEngine:
    global _engine
    with _engine_lock:
        if _engine is None:
            _engine = StockfishEngine()
            _engine.start()
        return _engine
