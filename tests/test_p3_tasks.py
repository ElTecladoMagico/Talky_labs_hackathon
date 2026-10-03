"""P3: cada tarea se puntúa contra golden de dev con el evaluador. Umbral = objetivo del hito (ver plan)."""
import json

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


# ---------------------------------------------------------------- periodificaciones: qué del histórico cuenta (fix/score-gaps)
def _accrual_db(rows, posted=()):
    """rows: (mes, referencia, periodo 'dd/mm–dd/mm/aaaa', importe) de periodificaciones históricas de V1 en 1100."""
    import sqlite3
    c = sqlite3.connect(":memory:")
    c.executescript(db.SHARED + "CREATE TABLE je_line(entry_id, company, posting_date, reference, header_text, source, account, debit, credit, partner, cost_center, wbs);")
    for i, (m, ref, period, amt) in enumerate(rows):
        e, day = f"E{i}", f"{m}-28"
        c.executemany("INSERT INTO je_line VALUES (?, '1100', ?, ?, ?, 'CLOSE_ACCRUAL', ?, ?, ?, ?, ?, NULL)",
                      [(e, day, ref, f"Periodificación gasto X {period}", "62800000", amt, 0, None, "CC-1"),
                       (e, day, ref, f"Periodificación gasto X {period}", "40090000", 0, amt, "V1", None)])
    c.executemany("INSERT INTO ap_result(doc_id, decision) VALUES (?, 'POST')", [(d,) for d in posted])
    return c


MONTHS = ["2026-02", "2026-03", "2026-04", "2026-05", "2026-06"]


def _partials(amount=1000):
    return [(m, f"ACCR-P{m}", f"16/{m[5:]}–{'28' if m == '2026-02' else '30' if m in ('2026-04', '2026-06') else '31'}/{m[5:]}/2026", amount)
            for m in MONTHS]


def test_accrual_estimate_ignores_late_cycle_entries():
    """Energía (dev V100029/1100): ciclos atrasados en 3 de 5 meses (14/02–15/03, 16/04–15/05, 17/05–15/06) no son consumo
    recurrente; mezclados con los tramos hasta fin de mes inflaban la mediana (+66 % frente al golden)."""
    late = [("2026-03", "ACCR-L1", "14/02–15/03/2026", 4000), ("2026-05", "ACCR-L2", "16/04–15/05/2026", 4000),
            ("2026-06", "ACCR-L3", "17/05–15/06/2026", 4000)]
    c = _accrual_db(_partials() + late, posted=[f"P{m}" for m in MONTHS] + ["L1", "L2", "L3"])
    (row,) = close.accruals(c, "2026-07")
    assert row["amount"] == 1000


def test_previous_month_end_accrual_still_unbilled_is_added():
    """Golden Fuenteclara: lo periodificado hasta el 30/06 cuya factura no llega (o llega rechazada) sigue pendiente en julio."""
    rows = _partials() + [("2026-06", "ACCR-BIM", "01/05–30/06/2026", 2400)]
    (row,) = close.accruals(_accrual_db(rows, posted=[f"P{m}" for m in MONTHS] + ["OTRA"]), "2026-07")
    assert row["amount"] == 1000 + 2400
    (row,) = close.accruals(_accrual_db(rows, posted=[f"P{m}" for m in MONTHS] + ["BIM"]), "2026-07")
    assert row["amount"] == 1000


def test_one_off_service_is_not_carried_over():
    """Golden V100210: un servicio puntual (27/06–27/06) periodificado en junio no se vuelve a periodificar en julio."""
    c = _accrual_db([("2026-02", "ACCR-A", "23/02–23/02/2026", 5000), ("2026-06", "ACCR-B", "27/06–27/06/2026", 4300)])
    assert close.accruals(c, "2026-07") == []


def test_without_ap_results_nothing_is_carried_over():
    """Sin ap_result (AP no ejecutado o caído) no se sabe qué facturas llegaron: no se arrastra nada (si no, se duplicaba todo)."""
    rows = _partials() + [("2026-06", "ACCR-BIM", "01/05–30/06/2026", 2400)]
    (row,) = close.accruals(_accrual_db(rows), "2026-07")
    assert row["amount"] == 1000


def test_accrual_covered_by_an_invoice_for_the_period_even_with_another_doc_id():
    """Test V100034/1100: lo periodificado 01/07–31/08 (ref. API004587) llega como API005261 con ese mismo periodo: está cubierto."""
    rows = _partials() + [("2026-06", "ACCR-BIM", "01/05–30/06/2026", 2400)]
    c = _accrual_db(rows, posted=[f"P{m}" for m in MONTHS])
    c.execute("INSERT INTO ap_result(doc_id, company, vendor_id, decision, data) VALUES ('OTRO', '1100', 'V1', 'POST', ?)",
              (json.dumps({"period_start": "2026-05-01", "period_end": "2026-06-30"}),))
    (row,) = close.accruals(c, "2026-07")
    assert row["amount"] == 1000
