import duckdb


def test_first_repeat_switch_and_exit_logic():
    con = duckdb.connect()
    con.execute("""
        CREATE TABLE firm_month(tin VARCHAR, month_dt DATE, sector VARCHAR);
        INSERT INTO firm_month VALUES
          ('A','2021-01-10','CONTROL'), ('A','2021-02-10','IT_CORE'), ('A','2021-04-10','IT_CORE'),
          ('B','2022-01-10','IT_CORE'), ('B','2022-02-10','IT_CORE');
    """)
    result = con.execute("""
      WITH ordered AS (
        SELECT *, lag(month_dt) OVER(PARTITION BY tin ORDER BY month_dt) prev_month,
                  lag(sector) OVER(PARTITION BY tin ORDER BY month_dt) prev_sector,
                  lead(month_dt) OVER(PARTITION BY tin ORDER BY month_dt) next_month,
                  row_number() OVER(PARTITION BY tin ORDER BY month_dt) rn
        FROM firm_month
      )
      SELECT tin, month_dt,
             (rn=1) first_entry,
             (rn>1 AND month_dt>prev_month+INTERVAL 1 MONTH) repeat_entry,
             coalesce(sector='IT_CORE' AND prev_sector<>'IT_CORE' AND month_dt=prev_month+INTERVAL 1 MONTH, false) switch_in,
             (next_month IS NULL OR next_month>month_dt+INTERVAL 1 MONTH) episode_exit
      FROM ordered ORDER BY tin, month_dt
    """).fetchall()
    assert result[0][2:] == (True, False, False, False)
    assert result[1][2:] == (False, False, True, True)
    assert result[2][2:] == (False, True, False, True)
    assert result[3][2:] == (True, False, False, False)


def test_retention_requires_continuous_first_episode():
    con = duckdb.connect()
    end = con.execute("""
      WITH x(month_dt, next_month) AS (VALUES (DATE '2022-01-10', DATE '2022-02-10'),
                                             (DATE '2022-02-10', DATE '2022-04-10'),
                                             (DATE '2022-04-10', NULL)),
      e AS (SELECT min(month_dt) FILTER (WHERE next_month IS NULL OR next_month>month_dt+INTERVAL 1 MONTH) episode_end FROM x)
      SELECT episode_end>=DATE '2022-07-10' FROM e
    """).fetchone()[0]
    assert end is False

