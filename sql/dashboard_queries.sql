-- Динамика фонда и событий (пример; приложение добавляет фильтры параметрами).
SELECT month_dt, sector,
       sum(stock) AS stock,
       sum(first_entries) AS first_entries,
       sum(repeat_entries) AS repeat_entries,
       sum(switch_in) AS switch_in,
       sum(registry_exits) AS registry_exits
FROM dashboard_monthly
GROUP BY month_dt, sector
ORDER BY month_dt, sector;

-- Удержание когорт на сопоставимых горизонтах.
SELECT cohort_month, sector,
       100.0 * sum(retained_6m) / nullif(sum(eligible_6m), 0) AS retention_6m_pct,
       100.0 * sum(retained_12m) / nullif(sum(eligible_12m), 0) AS retention_12m_pct
FROM dashboard_retention
GROUP BY cohort_month, sector
ORDER BY cohort_month, sector;

