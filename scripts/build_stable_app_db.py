from pathlib import Path
import duckdb

ROOT = Path(__file__).resolve().parents[1]
data = ROOT / "data"
private = data / "private"
db = data / "registry_dashboard.duckdb"

con = duckdb.connect(str(db))
for table, source in (
    ("dashboard_monthly", private / "dashboard_monthly_full.parquet"),
    ("dashboard_retention", private / "dashboard_retention_full.parquet"),
):
    escaped = str(source.resolve()).replace("'", "''")
    con.execute(f"CREATE TABLE {table} AS SELECT * FROM read_parquet('{escaped}')")
con.close()
print(db)

