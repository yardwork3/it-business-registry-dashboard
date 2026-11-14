from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import duckdb

from src.config import DEMO_MONTHLY, DEMO_RETENTION, LOCAL_DB, SOURCE_CSV, TEMP_DIR


SCHEMA = {
    "tin": "VARCHAR", "year": "INTEGER", "reg_number": "VARCHAR", "kind": "INTEGER",
    "category": "INTEGER", "org_name": "VARCHAR", "org_short_name": "VARCHAR",
    "activity_code_main": "VARCHAR", "region_iso_code": "VARCHAR", "region_code": "VARCHAR",
    "region": "VARCHAR", "area": "VARCHAR", "settlement": "VARCHAR",
    "settlement_type": "VARCHAR", "oktmo": "VARCHAR", "lat": "DOUBLE", "lon": "DOUBLE",
    "start_date": "DATE", "end_date": "DATE", "revenue": "DOUBLE",
    "expenditure": "DOUBLE", "employees_count": "INTEGER",
}


def q(path: Path) -> str:
    return str(path.resolve()).replace("'", "''")


def csv_source(path: Path) -> str:
    columns = "{" + ",".join(f"'{name}':'{dtype}'" for name, dtype in SCHEMA.items()) + "}"
    return (
        f"read_csv('{q(path)}', delim=';', header=true, quote='\"', nullstr='', "
        f"columns={columns}, strict_mode=true, encoding='utf-8')"
    )


def scalar(con: duckdb.DuckDBPyConnection, sql: str):
    return con.execute(sql).fetchone()[0]


def main() -> None:
    parser = argparse.ArgumentParser(description="Подготовка локального хранилища панели МСП")
    parser.add_argument("--source", type=Path, default=SOURCE_CSV)
    parser.add_argument("--database", type=Path, default=LOCAL_DB)
    parser.add_argument("--threads", type=int, default=10)
    parser.add_argument("--memory-limit", default="8GB")
    parser.add_argument("--resume", action="store_true", help="Не пересоздавать уже готовые eligible_tins и panel_reduced")
    args = parser.parse_args()

    source_path = args.source.resolve()
    db_path = args.database.resolve()
    if not source_path.exists():
        raise FileNotFoundError(source_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    started = time.time()

    con = duckdb.connect(str(db_path))
    con.execute(f"SET threads={args.threads}")
    con.execute(f"SET memory_limit='{args.memory_limit}'")
    con.execute(f"SET temp_directory='{q(TEMP_DIR)}'")
    con.execute("SET preserve_insertion_order=false")
    source = csv_source(source_path)

    if not args.resume:
        print("[1/8] Отбираю ИНН, когда-либо наблюдавшиеся в IT_CORE или CONTROL", flush=True)
        con.execute("DROP TABLE IF EXISTS eligible_tins")
        con.execute(f"""
        CREATE TABLE eligible_tins AS
        SELECT DISTINCT tin
        FROM {source}
        WHERE kind IN (1, 2)
          AND activity_code_main IS NOT NULL
          AND region_code IS NOT NULL
          AND (
            activity_code_main='62' OR activity_code_main LIKE '62.%' OR activity_code_main LIKE '63.1%'
            OR activity_code_main='70' OR activity_code_main LIKE '70.%'
            OR activity_code_main='71' OR activity_code_main LIKE '71.%'
            OR activity_code_main='82' OR activity_code_main LIKE '82.%'
          )
        """)

        print("[2/8] Создаю сокращённую таблицу необходимых полей; сохраняю полную историю ОКВЭД отобранных ИНН", flush=True)
        con.execute("DROP TABLE IF EXISTS panel_reduced")
        con.execute(f"""
        CREATE TABLE panel_reduced AS
        SELECT DISTINCT
            s.tin, s.year::USMALLINT AS year, s.kind::UTINYINT AS kind,
            s.category::UTINYINT AS category,
            nullif(trim(s.activity_code_main), '') AS activity_code_main,
            s.region, s.region_code, s.start_date, s.end_date,
            s.revenue, s.expenditure, s.employees_count
        FROM {source} s
        JOIN eligible_tins e USING (tin)
        WHERE s.kind IN (1, 2)
          AND s.activity_code_main IS NOT NULL
          AND s.region_code IS NOT NULL
          AND s.start_date IS NOT NULL
          AND s.end_date IS NOT NULL
          AND s.start_date <= s.end_date
        """)
    else:
        print("[1-2/8] Использую уже готовые eligible_tins и panel_reduced", flush=True)

    print("[3/8] Разворачиваю версии в состояния на 10-е число месяца", flush=True)
    con.execute("DROP TABLE IF EXISTS firm_month")
    con.execute("""
        CREATE TABLE firm_month AS
        WITH expanded AS (
          SELECT p.tin, p.start_date, p.end_date, p.kind, p.category,
                 p.activity_code_main, p.region, p.region_code,
                 gs.month_dt::DATE AS month_dt
          FROM panel_reduced p
          CROSS JOIN LATERAL generate_series(
              date_trunc('month', p.start_date) + INTERVAL 9 DAY,
              date_trunc('month', p.end_date) + INTERVAL 9 DAY,
              INTERVAL 1 MONTH
          ) gs(month_dt)
          WHERE gs.month_dt BETWEEN p.start_date AND p.end_date
        )
        SELECT tin, month_dt,
               arg_max(kind, struct_pack(start_date, end_date, activity_code_main)) AS kind,
               arg_max(category, struct_pack(start_date, end_date, activity_code_main)) AS category,
               arg_max(activity_code_main, struct_pack(start_date, end_date, activity_code_main)) AS activity_code_main,
               arg_max(region, struct_pack(start_date, end_date, activity_code_main)) AS region,
               arg_max(region_code, struct_pack(start_date, end_date, activity_code_main)) AS region_code,
               count(DISTINCT activity_code_main) AS concurrent_okved_n
        FROM expanded
        GROUP BY tin, month_dt
    """)

    print("[4/8] Классифицирую первые/повторные входы и непрерывные переходы", flush=True)
    con.execute("DROP TABLE IF EXISTS firm_month_events")
    con.execute("""
        CREATE TABLE firm_month_events AS
        WITH classified AS (
          SELECT *,
            CASE
              WHEN activity_code_main='62' OR activity_code_main LIKE '62.%' OR activity_code_main LIKE '63.1%' THEN 'IT_CORE'
              WHEN activity_code_main='70' OR activity_code_main LIKE '70.%'
                OR activity_code_main='71' OR activity_code_main LIKE '71.%'
                OR activity_code_main='82' OR activity_code_main LIKE '82.%' THEN 'CONTROL'
              ELSE 'OTHER' END AS sector,
            CASE
              WHEN activity_code_main='62' OR activity_code_main LIKE '62.%' THEN 'ИТ 62'
              WHEN activity_code_main LIKE '63.1%' THEN 'ИТ 63.1'
              WHEN activity_code_main='70' OR activity_code_main LIKE '70.%' THEN 'Контроль 70'
              WHEN activity_code_main='71' OR activity_code_main LIKE '71.%' THEN 'Контроль 71'
              WHEN activity_code_main='82' OR activity_code_main LIKE '82.%' THEN 'Контроль 82'
              ELSE 'Прочие' END AS industry
          FROM firm_month
        ), ordered AS (
          SELECT *,
                 lag(month_dt) OVER (PARTITION BY tin ORDER BY month_dt) AS prev_month,
                 lag(sector) OVER (PARTITION BY tin ORDER BY month_dt) AS prev_sector,
                 lead(month_dt) OVER (PARTITION BY tin ORDER BY month_dt) AS next_month,
                 row_number() OVER (PARTITION BY tin ORDER BY month_dt) AS observed_month_no
          FROM classified
        )
        SELECT *,
          (observed_month_no=1)::UTINYINT AS first_observed_entry,
          (observed_month_no>1 AND month_dt>prev_month+INTERVAL 1 MONTH)::UTINYINT AS repeat_entry,
          coalesce(sector='IT_CORE' AND prev_sector<>'IT_CORE' AND month_dt=prev_month+INTERVAL 1 MONTH, false)::UTINYINT AS switch_in,
          coalesce(sector<>'IT_CORE' AND prev_sector='IT_CORE' AND month_dt=prev_month+INTERVAL 1 MONTH, false)::UTINYINT AS switch_out,
          ((next_month IS NULL OR next_month>month_dt+INTERVAL 1 MONTH) AND month_dt<DATE '2024-06-10')::UTINYINT AS episode_exit
        FROM ordered
    """)

    print("[5/8] Строю обезличенные месячные агрегаты", flush=True)
    con.execute("DROP TABLE IF EXISTS dashboard_monthly")
    con.execute("""
        CREATE TABLE dashboard_monthly AS
        WITH stock_flow AS (
          SELECT month_dt, region, region_code, kind, category, sector, industry,
                 count(*) AS stock,
                 sum(first_observed_entry) AS first_entries,
                 sum(repeat_entry) AS repeat_entries,
                 sum(switch_in) AS switch_in,
                 sum(switch_out) AS switch_out,
                 0::BIGINT AS registry_exits
          FROM firm_month_events
          WHERE sector IN ('IT_CORE','CONTROL')
          GROUP BY ALL
        ), exits AS (
          SELECT (month_dt+INTERVAL 1 MONTH)::DATE AS month_dt,
                 region, region_code, kind, category, sector, industry,
                 0::BIGINT AS stock, 0::BIGINT AS first_entries, 0::BIGINT AS repeat_entries,
                 0::BIGINT AS switch_in, 0::BIGINT AS switch_out,
                 count(*) AS registry_exits
          FROM firm_month_events
          WHERE sector IN ('IT_CORE','CONTROL') AND episode_exit=1
          GROUP BY ALL
        )
        SELECT month_dt, region, region_code, kind, category, sector, industry,
               sum(stock)::BIGINT AS stock,
               sum(first_entries)::BIGINT AS first_entries,
               sum(repeat_entries)::BIGINT AS repeat_entries,
               sum(switch_in)::BIGINT AS switch_in,
               sum(switch_out)::BIGINT AS switch_out,
               sum(registry_exits)::BIGINT AS registry_exits
        FROM (SELECT * FROM stock_flow UNION ALL SELECT * FROM exits)
        GROUP BY ALL
    """)

    print("[6/8] Рассчитываю удержание первых непрерывных эпизодов через 6 и 12 месяцев", flush=True)
    con.execute("DROP TABLE IF EXISTS dashboard_retention")
    con.execute("""
        CREATE TABLE dashboard_retention AS
        WITH ordered AS (
          SELECT *,
                 lead(month_dt) OVER (PARTITION BY tin ORDER BY month_dt) AS lead_month,
                 min(month_dt) OVER (PARTITION BY tin) AS cohort_month
          FROM firm_month_events
        ), first_rows AS (
          SELECT * FROM ordered WHERE month_dt=cohort_month AND sector IN ('IT_CORE','CONTROL')
        ), first_ends AS (
          SELECT tin, min(month_dt) FILTER (
                   WHERE lead_month IS NULL OR lead_month>month_dt+INTERVAL 1 MONTH
                 ) AS first_episode_end
          FROM ordered GROUP BY tin
        ), cohort AS (
          SELECT f.tin, f.cohort_month, f.region, f.region_code, f.kind, f.category,
                 f.sector, f.industry, e.first_episode_end
          FROM first_rows f JOIN first_ends e USING(tin)
        )
        SELECT cohort_month, region, region_code, kind, category, sector, industry,
               count(*)::BIGINT AS cohort_n,
               count(*) FILTER (WHERE cohort_month+INTERVAL 6 MONTH<=DATE '2024-06-10')::BIGINT AS eligible_6m,
               count(*) FILTER (WHERE cohort_month+INTERVAL 6 MONTH<=DATE '2024-06-10'
                                  AND first_episode_end>=cohort_month+INTERVAL 6 MONTH)::BIGINT AS retained_6m,
               count(*) FILTER (WHERE cohort_month+INTERVAL 12 MONTH<=DATE '2024-06-10')::BIGINT AS eligible_12m,
               count(*) FILTER (WHERE cohort_month+INTERVAL 12 MONTH<=DATE '2024-06-10'
                                  AND first_episode_end>=cohort_month+INTERVAL 12 MONTH)::BIGINT AS retained_12m
        FROM cohort
        GROUP BY ALL
    """)

    print("[7/8] Экспортирую небольшой обезличенный демонабор", flush=True)
    con.execute(f"""
        COPY (
          SELECT month_dt, 'Все регионы' AS region, NULL::VARCHAR AS region_code,
                 kind, category, sector, industry,
                 sum(stock)::BIGINT AS stock, sum(first_entries)::BIGINT AS first_entries,
                 sum(repeat_entries)::BIGINT AS repeat_entries, sum(switch_in)::BIGINT AS switch_in,
                 sum(switch_out)::BIGINT AS switch_out, sum(registry_exits)::BIGINT AS registry_exits
          FROM dashboard_monthly
          WHERE month_dt BETWEEN DATE '2021-01-10' AND DATE '2024-06-10'
          GROUP BY month_dt, kind, category, sector, industry
        ) TO '{q(DEMO_MONTHLY)}' (FORMAT PARQUET, COMPRESSION ZSTD)
    """)
    con.execute(f"""
        COPY (
          SELECT cohort_month, 'Все регионы' AS region, NULL::VARCHAR AS region_code,
                 kind, category, sector, industry,
                 sum(cohort_n)::BIGINT AS cohort_n, sum(eligible_6m)::BIGINT AS eligible_6m,
                 sum(retained_6m)::BIGINT AS retained_6m, sum(eligible_12m)::BIGINT AS eligible_12m,
                 sum(retained_12m)::BIGINT AS retained_12m
          FROM dashboard_retention
          WHERE cohort_month BETWEEN DATE '2019-01-10' AND DATE '2023-06-10'
          GROUP BY cohort_month, kind, category, sector, industry
        ) TO '{q(DEMO_RETENTION)}' (FORMAT PARQUET, COMPRESSION ZSTD)
    """)

    print("[8/8] Записываю паспорт подготовки", flush=True)
    summary = {
        "source": str(source_path),
        "source_bytes": source_path.stat().st_size,
        "database": str(db_path),
        "duckdb_version": duckdb.__version__,
        "eligible_tins": scalar(con, "SELECT count(*) FROM eligible_tins"),
        "panel_reduced_rows": scalar(con, "SELECT count(*) FROM panel_reduced"),
        "firm_month_rows": scalar(con, "SELECT count(*) FROM firm_month"),
        "overlapping_firm_months": scalar(con, "SELECT count(*) FROM firm_month WHERE concurrent_okved_n>1"),
        "dashboard_monthly_rows": scalar(con, "SELECT count(*) FROM dashboard_monthly"),
        "dashboard_retention_rows": scalar(con, "SELECT count(*) FROM dashboard_retention"),
        "elapsed_seconds": round(time.time()-started, 2),
    }
    (PROJECT_ROOT / "data" / "preparation_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    con.close()


if __name__ == "__main__":
    main()

