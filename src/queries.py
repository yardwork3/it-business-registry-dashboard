from __future__ import annotations


def where_clause(filters: dict, alias: str = "") -> tuple[str, list]:
    p = f"{alias}." if alias else ""
    clauses = [f"{p}month_dt BETWEEN ? AND ?"]
    params: list = [filters["date_from"], filters["date_to"]]
    for column, key in (("region", "regions"), ("kind", "kinds"), ("category", "categories"), ("industry", "industries")):
        values = filters.get(key) or []
        if values:
            clauses.append(f"{p}{column} IN ({','.join('?' for _ in values)})")
            params.extend(values)
    return " AND ".join(clauses), params


def monthly_sql(relation: str, where: str) -> str:
    return f"""
        SELECT month_dt, sector,
               sum(stock) AS stock,
               sum(first_entries) AS first_entries,
               sum(repeat_entries) AS repeat_entries,
               sum(switch_in) AS switch_in,
               sum(switch_out) AS switch_out,
               sum(registry_exits) AS registry_exits
        FROM {relation}
        WHERE {where}
        GROUP BY month_dt, sector
        ORDER BY month_dt, sector
    """


def retention_sql(relation: str, filters: dict) -> tuple[str, list]:
    clauses = ["cohort_month BETWEEN ? AND ?"]
    params: list = [filters["date_from"], filters["date_to"]]
    for column, key in (("region", "regions"), ("kind", "kinds"), ("category", "categories"), ("industry", "industries")):
        values = filters.get(key) or []
        if values:
            clauses.append(f"{column} IN ({','.join('?' for _ in values)})")
            params.extend(values)
    sql = f"""
        SELECT cohort_month, sector,
               sum(cohort_n) AS cohort_n,
               sum(eligible_6m) AS eligible_6m,
               sum(retained_6m) AS retained_6m,
               sum(eligible_12m) AS eligible_12m,
               sum(retained_12m) AS retained_12m,
               100.0 * sum(retained_6m) / nullif(sum(eligible_6m), 0) AS retention_6m_pct,
               100.0 * sum(retained_12m) / nullif(sum(eligible_12m), 0) AS retention_12m_pct
        FROM {relation}
        WHERE {' AND '.join(clauses)}
        GROUP BY cohort_month, sector
        ORDER BY cohort_month, sector
    """
    return sql, params

