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
