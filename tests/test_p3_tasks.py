"""P3: cada tarea se puntúa contra golden de dev con el evaluador. Umbral = objetivo del hito (ver plan)."""
import pytest

from common import db
from participant import score
from tasks import ar_billing, ar_cash, close

GOLD = db.PHASES["dev"] / "golden"
# close: este fixture solo ejecuta ar_billing (sin AP ni banco de P1/P2): 0.686 aquí, 0.797 con el pipeline completo (run.py dev).
# El techo lo pone la estimación de ACCRUAL (consumo variable) y una decisión de P1 (API004559) que difiere del golden.
TARGET = {"ar_billing": 0.95, "ar_cash": 0.90, "close": 0.65}


@pytest.fixture(scope="module")
def conn(tmp_path_factory):
    c = db.build_db(db.PHASES["dev"], tmp_path_factory.mktemp("p3") / "dev.db")
    ar_billing.run(c)  # orden de run.py: ar_billing → ar_cash → close, sobre la misma conexión
    return c


def _score(fn, name, rows):
    return fn(score.load(GOLD / f"{name}.jsonl"), rows)[0]


def test_ar_billing_reaches_target(conn):
    assert _score(score.score_ar_billing, "ar_billing", ar_billing.billing_rows(conn)) >= TARGET["ar_billing"]


def test_ar_cash_reaches_target(conn):
    assert _score(score.score_ar_cash, "ar_cash", ar_cash.run(conn)) >= TARGET["ar_cash"]


def test_close_reaches_target(conn):
    assert _score(score.score_close, "close", close.run(conn)) >= TARGET["close"]


def test_close_fx_bank_uses_statement_closing_from_db(tmp_path):
    """El saldo final del extracto se lee de bank_statement (ya parseado al cargar), no reparseando los ficheros."""
    c = db.build_db(db.PHASES["dev"], tmp_path / "dev.db")
    base = next(r for r in close.fx(c, "2026-07") if r["item"] == "BANK:BANH-3100-USD")
    c.execute("UPDATE bank_statement SET closing = closing + 100000 WHERE account = 'BANH-3100-USD' AND month = '2026-07'")
    db.reset_run(c)  # el mismo hecho no se puede proponer dos veces
    moved = next(r for r in close.fx(c, "2026-07") if r["item"] == "BANK:BANH-3100-USD")
    assert moved["amount"] != base["amount"]


def test_close_fx_missing_statement_skips_only_that_item(tmp_path):
    """Sin extracto de la cuenta en divisa no se puede valorar: se omite esa partida, no se cae todo el cierre."""
    c = db.build_db(db.PHASES["dev"], tmp_path / "dev.db")
    c.execute("DELETE FROM bank_statement WHERE account = 'BANH-3100-USD'")
    items = [r["item"] for r in close.fx(c, "2026-07")]
    assert "BANK:BANH-3100-USD" not in items and any(i.startswith("GL:") for i in items)
