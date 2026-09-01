"""Persistent, transactionally atomic AI cost reservations."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from uuid import UUID

from ..ai_eval_productization import AICostLimits, AICostReservation

AI_COST_LEDGER_FILENAME = "ai-cost.sqlite3"


class SQLiteAICostLedger:
    def __init__(self, limits: AICostLimits, database_path: Path):
        if type(limits) is not AICostLimits or not isinstance(database_path, Path):
            raise TypeError("AI cost limits and database path required")
        self._limits = limits
        self._path = database_path
        database_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(database_path) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS ai_cost_reservation ("
                "workspace_id TEXT NOT NULL, session_id TEXT NOT NULL, "
                "tokens INTEGER NOT NULL, cost_microusd INTEGER NOT NULL)"
            )

    def authorize_and_reserve(
        self,
        workspace_id: str,
        session_id: str,
        *,
        input_tokens: int,
        output_tokens: int,
        estimated_cost_microusd: int,
    ) -> AICostReservation:
        self._validate(workspace_id, session_id)
        values = (input_tokens, output_tokens, estimated_cost_microusd)
        if any(type(value) is not int or value < 0 for value in values):
            raise ValueError("AI cost reservation values invalid")
        run_tokens = input_tokens + output_tokens
        if run_tokens > self._limits.max_run_tokens:
            raise ValueError("AI run token ceiling exceeded")
        if estimated_cost_microusd > self._limits.max_run_cost_microusd:
            raise ValueError("AI run cost ceiling exceeded")

        with sqlite3.connect(self._path, isolation_level=None, timeout=30) as connection:
            connection.execute("BEGIN IMMEDIATE")
            workspace_cost, workspace_tokens = connection.execute(
                "SELECT COALESCE(SUM(cost_microusd), 0), COALESCE(SUM(tokens), 0) "
                "FROM ai_cost_reservation WHERE workspace_id = ?",
                (workspace_id,),
            ).fetchone()
            session_cost, session_tokens = connection.execute(
                "SELECT COALESCE(SUM(cost_microusd), 0), COALESCE(SUM(tokens), 0) "
                "FROM ai_cost_reservation WHERE workspace_id = ? AND session_id = ?",
                (workspace_id, session_id),
            ).fetchone()
            workspace_cost += estimated_cost_microusd
            session_cost += estimated_cost_microusd
            workspace_tokens += run_tokens
            session_tokens += run_tokens
            self._enforce(workspace_cost, session_cost, workspace_tokens, session_tokens)
            connection.execute(
                "INSERT INTO ai_cost_reservation VALUES (?, ?, ?, ?)",
                (workspace_id, session_id, run_tokens, estimated_cost_microusd),
            )
            connection.execute("COMMIT")
        return AICostReservation(
            workspace_id, session_id, workspace_cost, session_cost, session_tokens
        )

    def snapshot(self, workspace_id: str, session_id: str) -> AICostReservation:
        self._validate(workspace_id, session_id)
        with sqlite3.connect(self._path) as connection:
            workspace_cost = connection.execute(
                "SELECT COALESCE(SUM(cost_microusd), 0) FROM ai_cost_reservation WHERE workspace_id = ?",
                (workspace_id,),
            ).fetchone()[0]
            session_cost, session_tokens = connection.execute(
                "SELECT COALESCE(SUM(cost_microusd), 0), COALESCE(SUM(tokens), 0) "
                "FROM ai_cost_reservation WHERE workspace_id = ? AND session_id = ?",
                (workspace_id, session_id),
            ).fetchone()
        return AICostReservation(workspace_id, session_id, workspace_cost, session_cost, session_tokens)

    def export_workspace(self, workspace_id: str) -> tuple[dict[str, object], ...]:
        self._validate(workspace_id, "export")
        with sqlite3.connect(self._path) as connection:
            rows = connection.execute(
                "SELECT session_id, tokens, cost_microusd FROM ai_cost_reservation "
                "WHERE workspace_id = ? ORDER BY rowid",
                (workspace_id,),
            ).fetchall()
        return tuple(
            {"session_id": session_id, "tokens": tokens, "cost_microusd": cost}
            for session_id, tokens, cost in rows
        )

    def import_workspace(self, workspace_id: str, rows: object) -> None:
        self._validate(workspace_id, "import")
        if type(rows) not in {list, tuple}:
            raise ValueError("AI cost reservation rows invalid")
        validated: list[tuple[str, str, int, int]] = []
        for row in rows:
            if type(row) is not dict or set(row) != {"session_id", "tokens", "cost_microusd"}:
                raise ValueError("AI cost reservation row invalid")
            session_id, tokens, cost = row["session_id"], row["tokens"], row["cost_microusd"]
            self._validate(workspace_id, session_id)
            if type(tokens) is not int or tokens < 0 or type(cost) is not int or cost < 0:
                raise ValueError("AI cost reservation row invalid")
            validated.append((workspace_id, session_id, tokens, cost))
        with sqlite3.connect(self._path, isolation_level=None, timeout=30) as connection:
            connection.execute("BEGIN IMMEDIATE")
            if connection.execute(
                "SELECT 1 FROM ai_cost_reservation WHERE workspace_id = ? LIMIT 1", (workspace_id,)
            ).fetchone() is not None:
                connection.execute("ROLLBACK")
                raise ValueError("AI cost workspace is not empty")
            connection.executemany("INSERT INTO ai_cost_reservation VALUES (?, ?, ?, ?)", validated)
            connection.execute("COMMIT")

    def _enforce(self, workspace_cost: int, session_cost: int, workspace_tokens: int, session_tokens: int) -> None:
        if session_cost > self._limits.max_session_cost_microusd:
            raise ValueError("AI session cost ceiling exceeded")
        if workspace_cost > self._limits.max_workspace_cost_microusd:
            raise ValueError("AI workspace cost ceiling exceeded")
        if self._limits.max_session_tokens is not None and session_tokens > self._limits.max_session_tokens:
            raise ValueError("AI session token ceiling exceeded")
        if self._limits.max_workspace_tokens is not None and workspace_tokens > self._limits.max_workspace_tokens:
            raise ValueError("AI workspace token ceiling exceeded")

    @staticmethod
    def _validate(workspace_id: str, session_id: str) -> None:
        try:
            parsed = UUID(workspace_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("workspace_id invalid") from exc
        if str(parsed) != workspace_id or type(session_id) is not str or not session_id.strip():
            raise ValueError("AI cost reservation identity invalid")
