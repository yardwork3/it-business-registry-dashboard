from pathlib import Path
import duckdb

ROOT = Path(__file__).resolve().parents[1]
data = ROOT / "data"
private = data / "private"
private.mkdir(parents=True, exist_ok=True)
db = data / "registry_dashboard.duckdb"

con = duckdb.connect(str(db), read_only=True)
for table, target in (
    ("panel_reduced", private / "panel_reduced.parquet"),
    ("dashboard_monthly", private / "dashboard_monthly_full.parquet"),
    ("dashboard_retention", private / "dashboard_retention_full.parquet"),
):
    escaped = str(target.resolve()).replace("'", "''")
    con.execute(f"COPY {table} TO '{escaped}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    print(target, target.stat().st_size)
con.close()

