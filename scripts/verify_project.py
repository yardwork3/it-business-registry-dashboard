from pathlib import Path
import json
import duckdb

ROOT = Path(__file__).resolve().parents[1]
db = ROOT / "data" / "registry_dashboard.duckdb"
con = duckdb.connect(str(db), read_only=True)

checks = {
    "tables": [row[0] for row in con.execute("SHOW TABLES").fetchall()],
    "dashboard_monthly_rows": con.execute("SELECT count(*) FROM dashboard_monthly").fetchone()[0],
    "dashboard_retention_rows": con.execute("SELECT count(*) FROM dashboard_retention").fetchone()[0],
    "legal_it_2022": dict(zip(
        ("first_entries", "repeat_entries", "switch_in"),
        con.execute("""
            SELECT sum(first_entries), sum(repeat_entries), sum(switch_in)
            FROM dashboard_monthly
            WHERE sector='IT_CORE' AND kind=1 AND year(month_dt)=2022
        """).fetchone(),
    )),
    "demo_monthly_has_tin": "tin" in [x[0].lower() for x in con.execute(
        f"DESCRIBE SELECT * FROM read_parquet('{str((ROOT/'data'/'demo_monthly.parquet').resolve()).replace("'", "''")}')"
    ).fetchall()],
}
print(json.dumps(checks, ensure_ascii=False, indent=2))
assert checks["tables"] == ["dashboard_monthly", "dashboard_retention"]
assert checks["legal_it_2022"] == {"first_entries": 8747, "repeat_entries": 216, "switch_in": 4082}
assert checks["demo_monthly_has_tin"] is False

