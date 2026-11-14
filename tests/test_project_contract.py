from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_sensitive_files_are_ignored():
    text = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "*.duckdb" in text
    assert "*.csv" in text
    assert "panel.csv" in text


def test_methodology_is_documented():
    text = (ROOT / "sql" / "01_prepare.sql").read_text(encoding="utf-8")
    for phrase in ("Первый вход", "Повторный вход", "Switch-in", "Выход"):
        assert phrase in text

