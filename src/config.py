from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_CSV = PROJECT_ROOT.parent / "panel.csv"
LOCAL_DB = PROJECT_ROOT / "data" / "registry_dashboard.duckdb"
DEMO_MONTHLY = PROJECT_ROOT / "data" / "demo_monthly.parquet"
DEMO_RETENTION = PROJECT_ROOT / "data" / "demo_retention.parquet"
TEMP_DIR = PROJECT_ROOT / "data" / "duckdb_tmp"

