from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import duckdb

from .config import DEMO_MONTHLY, DEMO_RETENTION, LOCAL_DB


@dataclass(frozen=True)
class DataSource:
    connection: duckdb.DuckDBPyConnection
    monthly_relation: str
    retention_relation: str
    mode: str


def connect(db_path: Path = LOCAL_DB) -> DataSource:
    if db_path.exists():
        con = duckdb.connect(str(db_path), read_only=True)
        return DataSource(con, "dashboard_monthly", "dashboard_retention", "Полные локальные агрегаты")
    if not DEMO_MONTHLY.exists() or not DEMO_RETENTION.exists():
        raise FileNotFoundError("Нет локальной DuckDB и демонстрационных Parquet. Запустите scripts/prepare_data.py.")
    con = duckdb.connect()
    con.execute(
    f"CREATE VIEW dashboard_monthly AS SELECT * FROM read_parquet('{str(DEMO_MONTHLY).replace(chr(39), chr(39)*2)}')"
)
con.execute(
    f"CREATE VIEW dashboard_retention AS SELECT * FROM read_parquet('{str(DEMO_RETENTION).replace(chr(39), chr(39)*2)}')"
)
    return DataSource(con, "dashboard_monthly", "dashboard_retention", "Обезличенный демонстрационный набор")


def rows(con: duckdb.DuckDBPyConnection, sql: str, params: list | None = None) -> list[dict]:
    cur = con.execute(sql, params or [])
    names = [item[0] for item in cur.description]
    return [dict(zip(names, row)) for row in cur.fetchall()]

