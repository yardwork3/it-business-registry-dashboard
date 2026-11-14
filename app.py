from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import plotly.express as px
import streamlit as st

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from src.db import connect, rows
from src.queries import monthly_sql, retention_sql, where_clause


st.set_page_config(page_title="ИТ-компании в реестре МСП", layout="wide")
st.title("Вход и удержание ИТ-компаний в реестре МСП")
st.caption("Структурная динамика реестра; выход из реестра не означает ликвидацию бизнеса.")

source = connect()
con = source.connection
st.sidebar.info(source.mode)

limits = rows(con, f"SELECT min(month_dt) lo, max(month_dt) hi FROM {source.monthly_relation}")[0]
default_lo = max(limits["lo"], date(2018, 1, 1))
period = st.sidebar.date_input("Период", value=(default_lo, limits["hi"]), min_value=limits["lo"], max_value=limits["hi"])
if len(period) != 2:
    st.stop()


def options(column: str):
    return [r[column] for r in rows(con, f"SELECT DISTINCT {column} FROM {source.monthly_relation} WHERE {column} IS NOT NULL ORDER BY 1")]


regions = st.sidebar.multiselect("Регион", options("region"))
kind_labels = {1: "Юридическое лицо", 2: "Индивидуальный предприниматель"}
kind_selected = st.sidebar.multiselect("Вид субъекта", list(kind_labels), format_func=lambda x: kind_labels[x])
category_labels = {1: "Микропредприятие", 2: "Малое", 3: "Среднее"}
category_selected = st.sidebar.multiselect("Категория", options("category"), format_func=lambda x: category_labels.get(x, str(x)))
industries = st.sidebar.multiselect("Отрасль", options("industry"))

filters = {
    "date_from": period[0], "date_to": period[1], "regions": regions,
    "kinds": kind_selected, "categories": category_selected, "industries": industries,
}
where, params = where_clause(filters)
monthly = rows(con, monthly_sql(source.monthly_relation, where), params)
ret_sql, ret_params = retention_sql(source.retention_relation, filters)
retention = rows(con, ret_sql, ret_params)

if not monthly:
    st.warning("Для выбранных фильтров данных нет.")
    st.stop()

latest = max(r["month_dt"] for r in monthly)
latest_rows = [r for r in monthly if r["month_dt"] == latest]
it_latest = sum(r["stock"] for r in latest_rows if r["sector"] == "IT_CORE")
control_latest = sum(r["stock"] for r in latest_rows if r["sector"] == "CONTROL")
c1, c2, c3 = st.columns(3)
c1.metric("ИТ-компании в последнем снимке", f"{it_latest:,}".replace(",", " "))
c2.metric("Контрольные отрасли", f"{control_latest:,}".replace(",", " "))
c3.metric("Последний снимок", latest.strftime("%d.%m.%Y"))

st.subheader("Динамика количества компаний")
st.plotly_chart(px.line(monthly, x="month_dt", y="stock", color="sector", markers=False,
                        labels={"month_dt": "Месяц", "stock": "Количество", "sector": "Группа"}), width="stretch")

flows = []
labels = {
    "first_entries": "Первые входы", "repeat_entries": "Повторные входы",
    "switch_in": "Переходы в ИТ", "registry_exits": "Выходы из реестра",
}
for row in monthly:
    for key, label in labels.items():
        if row["sector"] == "IT_CORE" or key != "switch_in":
            flows.append({"month_dt": row["month_dt"], "sector": row["sector"], "event": label, "value": row[key]})
st.subheader("Входы, переходы и выходы")
st.plotly_chart(px.line(flows, x="month_dt", y="value", color="event", line_dash="sector",
                        labels={"month_dt": "Месяц", "value": "Число событий", "event": "Событие", "sector": "Группа"}),
                width="stretch")

st.subheader("Удержание первых непрерывных эпизодов")
if retention:
    long_retention = []
    for row in retention:
        long_retention.extend([
            {"cohort_month": row["cohort_month"], "sector": row["sector"], "horizon": "6 месяцев", "retention": row["retention_6m_pct"]},
            {"cohort_month": row["cohort_month"], "sector": row["sector"], "horizon": "12 месяцев", "retention": row["retention_12m_pct"]},
        ])
    st.plotly_chart(px.line(long_retention, x="cohort_month", y="retention", color="sector", line_dash="horizon",
                            labels={"cohort_month": "Когорта первого входа", "retention": "Удержание, %", "sector": "Группа", "horizon": "Горизонт"}),
                    width="stretch")
else:
    st.info("Для выбранных когорт нет полного 6- или 12-месячного горизонта.")

with st.expander("Методологические определения"):
    st.markdown("""
- Состояния строятся на 10-е число каждого месяца по интервалам `start_date`–`end_date`.
- Первый вход — первое наблюдаемое присутствие ИНН в реестре; это не дата создания бизнеса.
- Повторный вход — возвращение после пропуска месячного снимка.
- Переход в ИТ — непрерывная смена не-ИТ кода на `62.*` или `63.1*` без пропуска месяца.
- Выход — первый отсутствующий месяц после непрерывного эпизода; это не юридическая ликвидация.
- Снимок 10 июня 2024 года цензурирован справа.
""")

