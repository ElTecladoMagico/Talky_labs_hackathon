"""P3 — cierre del mes: ACCRUAL, PREPAID, WIP_REVENUE, FX_REVAL, BAD_DEBT, DOUBTFUL_RECLASS.

Todo se estima del histórico del diario (fuentes CLOSE_*): el mes de cierre sale de tasks/close.json.
Los asientos de retrocesión del día 1 no se entregan."""
import calendar
import re
import statistics
from collections import defaultdict

from common import db
from common.je import make_je, propose
from tasks.ar_billing import q


def shift(month, k):
    y, m = map(int, month.split("-"))
    t = y * 12 + m - 1 - k
    return f"{t // 12}-{t % 12 + 1:02d}"


def split(total, weights):
    """Reparte total entre las líneas en proporción a weights; el resto de redondeo va a la mayor."""
    s = sum(weights)
    out = [round(total * w / s) for w in weights]
    out[max(range(len(out)), key=lambda i: weights[i])] += total - sum(out)
    return out


def accrual_estimate(series, month):
    """Mediana de los cierres de la misma fase del ciclo (cada L meses, L = 1..3 el de menor dispersión). ponytail: no modela cada factura futura."""
    best = None
    for L in (1, 2, 3):
        ph = [v for v in (series.get(shift(month, k * L)) for k in range(1, 9 // L + 1)) if v]
        if len(ph) < 2:
            continue
        disp = statistics.mean(abs(a - b) / max(a, b) for a, b in zip(ph, ph[1:]))
        if best is None or disp < best[0] - 0.03:
            best = (disp, ph[:3])
    return round(statistics.median(best[1])) if best else None


def accruals(conn, month):
    series, tmpl = defaultdict(dict), {}
    for r in q(conn, """SELECT company, partner, substr(posting_date, 1, 7) m, SUM(credit - debit) amt FROM je_line
                        WHERE account = '40090000' AND source = 'CLOSE_ACCRUAL' AND partner LIKE 'V%' GROUP BY 1, 2, 3"""):
        series[(r["company"], r["partner"])][r["m"]] = r["amt"]
    rows = []
    for (company, vendor), s in sorted(series.items()):
        if not any(s.get(shift(month, k)) for k in (1, 2)):
            continue  # ya no se periodifica a este proveedor
        amt = accrual_estimate(s, month)
        if not amt:
            continue
        last = max(m for m in s if s[m])
        dr = q(conn, """SELECT account, cost_center, wbs, SUM(debit) d FROM je_line WHERE company = ? AND source = 'CLOSE_ACCRUAL' AND debit > 0
                        AND entry_id IN (SELECT entry_id FROM je_line WHERE partner = ? AND source = 'CLOSE_ACCRUAL' AND substr(posting_date, 1, 7) = ?)
                        GROUP BY 1, 2, 3""", company, vendor, last)
        lines = [dict(account=d["account"], debit=a, cost_center=d["cost_center"], wbs=d["wbs"]) for d, a in zip(dr, split(amt, [d["d"] for d in dr]))]
        lines.append(dict(account="40090000", credit=amt, partner=vendor, assignment=f"ACCR-{vendor}-{month.replace('-', '')}"))
        je = make_je(company, lines)
        propose(conn, f"close:accrual:{company}:{vendor}:{month}", "P3", "close", je)
        rows.append(dict(type="ACCRUAL", company=company, vendor=vendor, amount=amt, journal_entry=je))
    return rows


def prepaid(conn, month):
    """Mensualidad siguiente de cada gasto anticipado en curso: saldo pendiente de la 48 / cuotas que faltan."""
    rows, prev = [], shift(month, 1)
    for r in q(conn, """SELECT company, reference, header_text, SUM(CASE WHEN account = '48000000' THEN debit - credit END) bal, MAX(posting_date) last
                        FROM je_line WHERE source = 'CLOSE_PREPAID' AND reference LIKE 'PREP-%' GROUP BY company, reference"""):
        n = int(re.search(r"/(\d+)\)", r["header_text"]).group(1))
        k = q(conn, "SELECT COUNT(DISTINCT entry_id) c FROM je_line WHERE reference = ? AND source = 'CLOSE_PREPAID'", r["reference"])[0]["c"]
        if r["last"][:7] != prev or k >= n or r["bal"] <= 0:
            continue
        amt = r["bal"] if k + 1 == n else round(r["bal"] / (n - k))
        exp = q(conn, "SELECT account, cost_center, wbs FROM je_line WHERE reference = ? AND source = 'CLOSE_PREPAID' AND account != '48000000' LIMIT 1", r["reference"])[0]
        je = make_je(r["company"], [dict(account=exp["account"], debit=amt, cost_center=exp["cost_center"], wbs=exp["wbs"]), dict(account="48000000", credit=amt)])
        propose(conn, f"close:prepaid:{r['reference']}:{month}", "P3", "close", je)
        rows.append(dict(type="PREPAID", company=r["company"], invoice=r["reference"][5:], amount=-amt, journal_entry=je))
    return rows


STEPS = {"ACCRUAL": accruals, "PREPAID": prepaid}


def run(conn):
    cfg = db.get_json(conn, "tasks/close")
    rows = []
    for step in cfg["steps"]:
        if step in STEPS:
            rows += STEPS[step](conn, cfg["month"])
    return rows
