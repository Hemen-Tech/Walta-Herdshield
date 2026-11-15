from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "admas.db"


def get_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_db() -> None:
    with get_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS model_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                region TEXT NOT NULL,
                assessment_date TEXT NOT NULL,
                risk_score REAL NOT NULL,
                risk_level TEXT NOT NULL,
                summary_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS api_keys (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key_name TEXT NOT NULL UNIQUE,
                key_value TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.execute(
            """
            INSERT OR IGNORE INTO api_keys (key_name, key_value)
            VALUES ('default_admin', 'admas-admin-demo-key')
            """
        )


def save_model_run(region: str, assessment_date: str, risk_score: float, risk_level: str, summary: dict) -> int:
    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO model_runs (region, assessment_date, risk_score, risk_level, summary_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (region, assessment_date, risk_score, risk_level, __import__('json').dumps(summary)),
        )
        return int(cursor.lastrowid)


def list_model_runs(limit: int = 20) -> list[dict]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT region, assessment_date, risk_score, risk_level, summary_json, created_at
            FROM model_runs
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def validate_api_key(provided_key: str | None) -> bool:
    if not provided_key:
        return False
    with get_connection() as connection:
        row = connection.execute(
            "SELECT 1 FROM api_keys WHERE key_value = ?",
            (provided_key,),
        ).fetchone()
    return row is not None
