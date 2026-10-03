"""P3 — cierre del mes: ACCRUAL, PREPAID, WIP_REVENUE, FX_REVAL, BAD_DEBT, DOUBTFUL_RECLASS.

Todo se estima del histórico del diario (fuentes CLOSE_*): el mes de cierre sale de tasks/close.json.
Los asientos de retrocesión del día 1 no se entregan."""
import json
import re
import statistics
from collections import defaultdict
from datetime import date

from common import db, statements
from common.je import make_je, propose
from tasks import ar_billing
from tasks.ar_billing import certification, month_end, q


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
    """Mediana de los cinco últimos cierres de la misma fase del ciclo (cada L meses, L = 1..3 el de menor dispersión). ponytail: no modela cada factura futura; el consumo varía ±15-50 % de un ciclo a otro."""
    best = None
    for L in (1, 2, 3):
        ph = [v for v in (series.get(shift(month, k * L)) for k in range(1, 9 // L + 1)) if v]
        if len(ph) < 2:
            continue
        disp = statistics.mean(abs(a - b) / max(a, b) for a, b in zip(ph, ph[1:]))
        if best is None or disp < best[0] - 0.03:
            best = (disp, [v for v in (series.get(shift(month, k * L)) for k in range(1, 5 * L + 1)) if v][:5])
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
    return rows + prepaid_new(conn, month)


def months(a, b):
    return (int(b[:4]) * 12 + int(b[5:7])) - (int(a[:4]) * 12 + int(a[5:7]))


def prepaid_new(conn, month):
    """Facturas contabilizadas por P1 cuya cobertura es semestral o anual: se difiere a la 48 lo que cae en los meses siguientes al cierre (el mes en curso se gasta)."""
    rows = []
    for r in q(conn, "SELECT doc_id, company, data FROM ap_result WHERE decision IN ('POST', 'POST_PAYMENT_BLOCK') ORDER BY doc_id"):
        d = json.loads(r["data"])
        ps, pe = d.get("period_start"), d.get("period_end")
        if not ps or not pe or d.get("document_type") != "INVOICE" or ps[:7] > month:
            continue
        n, left = months(ps, pe) + 1, months(month, pe[:7])
        if n < 6 or left <= 0 or q(conn, "SELECT 1 FROM je_line WHERE reference = ? AND source = 'CLOSE_PREPAID' LIMIT 1", f"PREP-{r['doc_id']}"):
            continue
        je = q(conn, "SELECT lines FROM proposed_je WHERE event_key = ?", f"ap:{r['doc_id']}")
        if not je:
            continue
        exp = defaultdict(int)
        for l in json.loads(je[0]["lines"]):
            if l["debit"] and not l["account"].startswith("47") and not l["account"].startswith("40"):
                exp[(l["account"], l.get("cost_center"), l.get("wbs"))] += l["debit"]
        amt = sum(exp.values()) * left // n
        keys = list(exp)
        lines = [dict(account="48000000", debit=amt)] + [dict(account=a, credit=c, cost_center=cc, wbs=w) for (a, cc, w), c in zip(keys, split(amt, [exp[k] for k in keys]))]
        out = make_je(r["company"], lines)
        propose(conn, f"close:prepaid:{r['doc_id']}:{month}", "P3", "close", out)
        rows.append(dict(type="PREPAID", company=r["company"], invoice=r["doc_id"], amount=amt, journal_entry=out))
    return rows


def wip(conn, month):
    """Obra ejecutada pendiente de certificar: las SKIP_PENDING_APPROVAL de la facturación (Dr 43090000 / Cr 71300000, se retrocede el día 1)."""
    root, rows = db.phase_dir(conn), []
    contracts = {r["id"]: r for r in q(conn, "SELECT id, project FROM sales_contracts")}
    for b in ar_billing.billing_rows(conn):
        if b["expected"] != "SKIP_PENDING_APPROVAL":
            continue
        item = json.loads((root / "inbox/ar/billing" / b["billing_item"] / "item.json").read_text())
        path = root / "inbox/ar/billing" / b["billing_item"] / item["documents"][0]
        cert = certification(path)
        n = int(re.search(r"N.\s*(\d+)", ar_billing.pdf_lines(path)[0]).group(1))
        amt, project = cert["origin"] - cert["previous"], contracts[b["contract"]]["project"]
        je = make_je(b["company"], [dict(account="43090000", debit=amt, partner=b["customer"], assignment=f"CERT-{project}-{n:02d}"),
                                    dict(account="71300000", credit=amt, wbs=f"{project}.01")])
        propose(conn, f"close:wip:{b['billing_item']}", "P3", "close", je)
        rows.append(dict(type="WIP_REVENUE", company=b["company"], billing_item=b["billing_item"], amount=amt, journal_entry=je))
    return rows


def due_dates(conn):
    due = {r["id"]: r["due_date"] for r in q(conn, "SELECT id, due_date FROM ar_invoices")}
    for b in ar_billing.billing_rows(conn):
        if b["expected"] == "INVOICE":
            due[b["journal_entry"]["lines"][0]["assignment"]] = b["invoice"]["due_date"]
    return due


def doubtful_customers(conn):
    return {r["id"]: json.loads(r["insolvency"]) for r in q(conn, "SELECT id, insolvency FROM customers WHERE insolvency IS NOT NULL")}


def doubtful(conn, month):
    """En el mes del concurso: el saldo vivo del cliente pasa de 43000000 a 43600000 factura a factura."""
    rows = []
    for cust, ins in doubtful_customers(conn).items():
        if ins["declared_on"][:7] != month:
            continue
        for company in {r["company"] for r in q(conn, "SELECT DISTINCT company FROM ledger WHERE account = '43000000' AND partner = ?", cust)}:
            inv = q(conn, """SELECT assignment, SUM(debit - credit) bal FROM ledger WHERE company = ? AND account = '43000000' AND partner = ?
                             GROUP BY 1 HAVING SUM(debit - credit) > 0 ORDER BY 1""", company, cust)
            lines = [l for i in inv for l in (dict(account="43600000", debit=i["bal"], partner=cust, assignment=i["assignment"]),
                                              dict(account="43000000", credit=i["bal"], partner=cust, assignment=i["assignment"]))]
            if lines:
                je = make_je(company, lines)
                propose(conn, f"close:doubtful:{company}:{cust}:{month}", "P3", "close", je)
                rows.append(dict(type="DOUBTFUL_RECLASS", company=company, customer=cust, amount=sum(i["bal"] for i in inv), journal_entry=je))
    return rows


def baddebt(conn, month):
    """Deterioro de clientes privados y comunidades: 50 % de lo vencido a más de 180 días, 100 % a más de 365; en concurso, 100 % de todo su saldo (garantías incluidas)."""
    me, due, ins = month_end(month), due_dates(conn), doubtful_customers(conn)
    cust = {r["id"]: r for r in q(conn, "SELECT id, kind, [group] g FROM customers")}
    need, prov = defaultdict(float), {}
    for r in q(conn, """SELECT company, partner, assignment, account, SUM(debit - credit) bal FROM ledger
                        WHERE account IN ('43000000', '43000900', '43600000') AND partner LIKE 'C%' GROUP BY 1, 2, 3, 4 HAVING SUM(debit - credit) != 0"""):
        c = cust.get(r["partner"])
        if not c or c["kind"] in ("public", "group") or c["g"]:
            continue
        k = (r["company"], r["partner"])
        if r["partner"] in ins and ins[r["partner"]]["declared_on"] <= me.isoformat():
            need[k] += r["bal"]
        elif r["account"] == "43000000" and r["bal"] > 0 and due.get(r["assignment"]):
            age = (me - date.fromisoformat(due[r["assignment"]])).days
            need[k] += r["bal"] * (1 if age > 365 else 0.5 if age > 180 else 0)
    for r in q(conn, "SELECT company, partner, SUM(credit - debit) p FROM ledger WHERE account = '49000000' GROUP BY 1, 2"):
        prov[(r["company"], r["partner"])] = r["p"]
    rows = []
    for (company, partner) in sorted(set(need) | set(prov)):
        amt = round(need.get((company, partner), 0)) - prov.get((company, partner), 0)
        if abs(amt) <= 2:  # redondeo de céntimos de la provisión anterior
            continue
        lines = [dict(account="69400000", debit=amt), dict(account="49000000", credit=amt, partner=partner)] if amt > 0 else \
                [dict(account="49000000", debit=-amt, partner=partner), dict(account="79400000", credit=-amt)]
        je = make_je(company, lines)
        propose(conn, f"close:baddebt:{company}:{partner}:{month}", "P3", "close", je)
        rows.append(dict(type="BAD_DEBT", company=company, customer=partner, amount=amt, journal_entry=je))
    return rows


def fx_rate(conn, cur, local, day):
    """Unidades de moneda local por unidad de `cur`, vía EUR (SYN-BCE del último día publicado), con el 1/tipo redondeado a 6 decimales como el histórico."""
    return round(1 / db.fx_rate(conn, cur, day), 6) * db.fx_rate(conn, local, day)


def fx_entry(conn, month, company, item, account, partner, assignment, foreign, book, cur, local, day):
    """book = saldo contable con signo (debe − haber); foreign = importe en divisa en valor absoluto. amount = valor a cierre − valor contable (en absoluto)."""
    amt = round(foreign * fx_rate(conn, cur, local, day)) - abs(book)
    if not amt:
        return None
    asset = book > 0
    gain = (amt > 0) == asset  # activo que sube o pasivo que baja = ganancia (76800000); al revés, pérdida (66800000)
    side = "debit" if (amt > 0) == asset else "credit"
    if not asset:
        side = "credit" if amt > 0 else "debit"
    lines = [dict(account=account, partner=partner, assignment=assignment, **{side: abs(amt)}),
             dict(account="76800000" if gain else "66800000", **{"credit" if gain else "debit": abs(amt)})]
    je = make_je(company, lines)
    propose(conn, f"close:fx:{item}:{month}", "P3", "close", je)
    return dict(type="FX_REVAL", company=company, item=item, amount=amt, journal_entry=je)


def fx(conn, month):
    """Partidas abiertas en divisa a tipo de cierre: facturas AP (con su moneda original), préstamo e intereses intragrupo en EUR y cuenta bancaria en USD."""
    day = month_end(month).isoformat()
    cur_of = {r["code"]: r["currency"] for r in q(conn, "SELECT code, currency FROM companies")}
    rows = []
    for r in q(conn, "SELECT doc_id, company, data FROM ap_result WHERE decision IN ('POST', 'POST_PAYMENT_BLOCK') ORDER BY doc_id"):
        d = json.loads(r["data"])
        local, src = cur_of[r["company"]], d.get("source_currency")
        if not src or src == local or d.get("document_type") == "DOWN_PAYMENT_REQUEST":
            continue
        v = q(conn, """SELECT account, SUM(debit - credit) bal FROM ledger WHERE company = ? AND partner = ? AND assignment = ?
                       AND account IN ('40000000', '41000000', '40300000') GROUP BY 1 HAVING SUM(debit - credit) < 0""", r["company"], d["vendor_id"], d["invoice_number"])
        if v:
            rows.append(fx_entry(conn, month, r["company"], f"AP:{r['doc_id']}", v[0]["account"], d["vendor_id"], d["invoice_number"],
                                 abs(d["source_amounts"]["payable"]), v[0]["bal"], src, local, day))
    banks = {b["gl_account"]: b for b in q(conn, "SELECT id, company, gl_account, currency FROM bank_accounts")}
    for g in q(conn, """SELECT company, account, currency, MAX(partner) partner, MAX(assignment) assignment, SUM(amount_doc * CASE WHEN debit > 0 THEN 1 ELSE -1 END) f
                        FROM je_line WHERE source NOT LIKE 'CLOSE_FX%' GROUP BY 1, 2, 3 HAVING f != 0"""):
        local = cur_of[g["company"]]
        if g["currency"] == local or g["account"] in banks or g["account"][:2] not in ("16", "24", "52", "55"):
            continue  # solo partidas financieras e intragrupo; gastos, IVA e inmovilizado se quedan al cambio histórico
        book = q(conn, "SELECT SUM(debit - credit) b FROM je_line WHERE company = ? AND account = ? AND currency = ? AND source NOT LIKE 'CLOSE_FX%'", g["company"], g["account"], g["currency"])[0]["b"]
        rows.append(fx_entry(conn, month, g["company"], f"GL:{g['account']}", g["account"], g["partner"], g["assignment"], abs(g["f"]), book, g["currency"], local, day))
    for b in banks.values():
        local = cur_of[b["company"]]
        if b["currency"] == local:
            continue
        files = [p for p in (db.phase_dir(conn) / "bank" / b["id"]).glob(f"{month}.*") if not p.name.endswith(".lines.jsonl")]
        closing = statements.parse(files[0])["closing"]
        book = q(conn, "SELECT SUM(debit - credit) b FROM ledger WHERE company = ? AND account = ?", b["company"], b["gl_account"])[0]["b"]
        rows.append(fx_entry(conn, month, b["company"], f"BANK:{b['id']}", b["gl_account"], None, None, closing, book, b["currency"], local, day))
    return [r for r in rows if r]


STEPS = {"ACCRUAL": accruals, "PREPAID": prepaid, "WIP_REVENUE": wip, "FX_REVAL": fx, "DOUBTFUL_RECLASS": doubtful, "BAD_DEBT": baddebt}


def run(conn):
    """Se hacen siempre los seis pasos (dev solo lista dos en close.json pero su referencia incluye los demás); el orden importa: el concurso antes del deterioro."""
    month = db.get_json(conn, "tasks/close")["month"]
    return [r for step in STEPS.values() for r in step(conn, month)]
