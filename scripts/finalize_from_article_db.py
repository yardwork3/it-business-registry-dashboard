from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import duckdb

from src.config import DEMO_MONTHLY, DEMO_RETENTION, LOCAL_DB

ARTICLE_DB = ROOT.parent / "panel.duckdb"


def q(path: Path) -> str:
    return str(path.resolve()).replace("'", "''")


def main() -> None:
    started = time.time()
    con = duckdb.connect(str(LOCAL_DB))
    con.execute("SET threads=10")
    con.execute("SET memory_limit='8GB'")
    con.execute(f"ATTACH '{q(ARTICLE_DB)}' AS article (READ_ONLY)")
    con.execute("CREATE OR REPLACE TABLE region_lookup AS SELECT region_code, any_value(region) region FROM panel_reduced GROUP BY region_code")

    sector = "CASE WHEN e.okved='62' OR e.okved LIKE '62.%' OR e.okved LIKE '63.1%' THEN 'IT_CORE' WHEN e.okved='70' OR e.okved LIKE '70.%' OR e.okved='71' OR e.okved LIKE '71.%' OR e.okved='82' OR e.okved LIKE '82.%' THEN 'CONTROL' ELSE 'OTHER' END"
    industry = "CASE WHEN e.okved='62' OR e.okved LIKE '62.%' THEN 'ИТ 62' WHEN e.okved LIKE '63.1%' THEN 'ИТ 63.1' WHEN e.okved='70' OR e.okved LIKE '70.%' THEN 'Контроль 70' WHEN e.okved='71' OR e.okved LIKE '71.%' THEN 'Контроль 71' WHEN e.okved='82' OR e.okved LIKE '82.%' THEN 'Контроль 82' ELSE 'Прочие' END"

    print("[1/4] Месячные обезличенные агрегаты", flush=True)
    con.execute("DROP TABLE IF EXISTS dashboard_monthly")
    con.execute(f"""
      CREATE TABLE dashboard_monthly AS
      WITH base AS (
        SELECT e.*, {sector} sector2, {industry} industry2,
               lead(e.month_dt) OVER(PARTITION BY e.tin ORDER BY e.month_dt) next_month
        FROM article.firm_month_events e
      ), stock_flow AS (
        SELECT e.month_dt, coalesce(r.region, 'Код '||e.region_code) region, e.region_code,
               e.kind, e.category, e.sector2 sector, e.industry2 industry,
               count(*) stock, sum(e.first_observed_entry) first_entries,
               sum(e.repeat_entry) repeat_entries, sum(e.switch_in) switch_in,
               sum(e.switch_out) switch_out, 0::BIGINT registry_exits
        FROM base e LEFT JOIN region_lookup r USING(region_code)
        WHERE e.sector2 IN ('IT_CORE','CONTROL')
        GROUP BY ALL
      ), exits AS (
        SELECT (e.month_dt+INTERVAL 1 MONTH)::DATE month_dt,
               coalesce(r.region, 'Код '||e.region_code) region, e.region_code,
               e.kind, e.category, e.sector2 sector, e.industry2 industry,
               0::BIGINT stock, 0::BIGINT first_entries, 0::BIGINT repeat_entries,
               0::BIGINT switch_in, 0::BIGINT switch_out, count(*) registry_exits
        FROM base e LEFT JOIN region_lookup r USING(region_code)
        WHERE e.sector2 IN ('IT_CORE','CONTROL')
          AND (e.next_month IS NULL OR e.next_month>e.month_dt+INTERVAL 1 MONTH)
          AND e.month_dt<DATE '2024-06-10'
        GROUP BY ALL
      )
      SELECT month_dt, region, region_code, kind, category, sector, industry,
             sum(stock)::BIGINT stock, sum(first_entries)::BIGINT first_entries,
             sum(repeat_entries)::BIGINT repeat_entries, sum(switch_in)::BIGINT switch_in,
             sum(switch_out)::BIGINT switch_out, sum(registry_exits)::BIGINT registry_exits
      FROM (SELECT * FROM stock_flow UNION ALL SELECT * FROM exits)
      GROUP BY ALL
    """)

    print("[2/4] Удержание когорт", flush=True)
    con.execute("DROP TABLE IF EXISTS dashboard_retention")
    con.execute(f"""
      CREATE TABLE dashboard_retention AS
      WITH base AS (
        SELECT e.*, {sector} sector2, {industry} industry2,
               lead(e.month_dt) OVER(PARTITION BY e.tin ORDER BY e.month_dt) lead_month,
               min(e.month_dt) OVER(PARTITION BY e.tin) cohort_month
        FROM article.firm_month_events e
      ), first_rows AS (
        SELECT * FROM base WHERE month_dt=cohort_month AND sector2 IN ('IT_CORE','CONTROL')
      ), first_ends AS (
        SELECT tin, min(month_dt) FILTER(WHERE lead_month IS NULL OR lead_month>month_dt+INTERVAL 1 MONTH) first_episode_end
        FROM base GROUP BY tin
      )
      SELECT f.cohort_month, coalesce(r.region, 'Код '||f.region_code) region, f.region_code,
             f.kind, f.category, f.sector2 sector, f.industry2 industry,
             count(*)::BIGINT cohort_n,
             count(*) FILTER(WHERE f.cohort_month+INTERVAL 6 MONTH<=DATE '2024-06-10')::BIGINT eligible_6m,
             count(*) FILTER(WHERE f.cohort_month+INTERVAL 6 MONTH<=DATE '2024-06-10' AND e.first_episode_end>=f.cohort_month+INTERVAL 6 MONTH)::BIGINT retained_6m,
             count(*) FILTER(WHERE f.cohort_month+INTERVAL 12 MONTH<=DATE '2024-06-10')::BIGINT eligible_12m,
             count(*) FILTER(WHERE f.cohort_month+INTERVAL 12 MONTH<=DATE '2024-06-10' AND e.first_episode_end>=f.cohort_month+INTERVAL 12 MONTH)::BIGINT retained_12m
      FROM first_rows f JOIN first_ends e USING(tin) LEFT JOIN region_lookup r USING(region_code)
      GROUP BY ALL
    """)

    print("[3/4] Демонстрационные Parquet", flush=True)
    con.execute(f"COPY (SELECT month_dt, 'Все регионы' region, NULL::VARCHAR region_code, kind, category, sector, industry, sum(stock)::BIGINT stock, sum(first_entries)::BIGINT first_entries, sum(repeat_entries)::BIGINT repeat_entries, sum(switch_in)::BIGINT switch_in, sum(switch_out)::BIGINT switch_out, sum(registry_exits)::BIGINT registry_exits FROM dashboard_monthly WHERE month_dt BETWEEN DATE '2021-01-10' AND DATE '2024-06-10' GROUP BY month_dt,kind,category,sector,industry) TO '{q(DEMO_MONTHLY)}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    con.execute(f"COPY (SELECT cohort_month, 'Все регионы' region, NULL::VARCHAR region_code, kind, category, sector, industry, sum(cohort_n)::BIGINT cohort_n, sum(eligible_6m)::BIGINT eligible_6m, sum(retained_6m)::BIGINT retained_6m, sum(eligible_12m)::BIGINT eligible_12m, sum(retained_12m)::BIGINT retained_12m FROM dashboard_retention WHERE cohort_month BETWEEN DATE '2019-01-10' AND DATE '2023-06-10' GROUP BY cohort_month,kind,category,sector,industry) TO '{q(DEMO_RETENTION)}' (FORMAT PARQUET, COMPRESSION ZSTD)")

    print("[4/4] Паспорт", flush=True)
    summary_path = ROOT / "data" / "preparation_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}
    summary.update({
        "event_layer_source": str(ARTICLE_DB),
        "event_layer_note": "Ранее рассчитан из того же panel.csv для article_DIGITAL2027 по тем же определениям; panel_reduced текущего проекта построен прямым чтением CSV.",
        "panel_reduced_rows": con.execute("SELECT count(*) FROM panel_reduced").fetchone()[0],
        "dashboard_monthly_rows": con.execute("SELECT count(*) FROM dashboard_monthly").fetchone()[0],
        "dashboard_retention_rows": con.execute("SELECT count(*) FROM dashboard_retention").fetchone()[0],
        "article_firm_month_rows": con.execute("SELECT count(*) FROM article.firm_month").fetchone()[0],
        "overlapping_firm_months": con.execute("SELECT count(*) FROM article.firm_month WHERE concurrent_okved_n>1").fetchone()[0],
        "finalization_seconds": round(time.time()-started, 2),
    })
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    con.close()


if __name__ == "__main__":
    main()

