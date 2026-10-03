"""P2 · Conciliación intragrupo (§6). Un detector por causa sobre el diario (los saldos 433/403 no se compensan con los cobros
en este ERP, así que comparar saldos no sirve). `detect` es puro; `run(conn)` carga, propone los ajustes y devuelve ic.jsonl.
El barrido de pooling sin registrar lo asienta bank_rec: aquí se declara con adjustment [].
"""
import calendar
import sqlite3
import sys
from collections import defaultdict

from common import db
from common.je import make_je, norm_num, propose

IC_ACC = {"55200000", "43300000", "55210000", "55220000", "24230000", "16330000"}  # el socio es un código de sociedad


def warn(msg):
    print(f"[ic] AVISO: {msg}", file=sys.stderr)


def _amt(l):
    return l["debit"] - l["credit"]


def _l(company, account, amount, **kw):
    return dict(company=company, account=account, debit=max(amount, 0), credit=max(-amount, 0), **kw)


def _row(pair, account, cause, amount, responsible, lines):
    adj = make_je(responsible, lines)["lines"] if lines else []
    return {"pair": sorted(pair), "account": account, "cause": cause, "amount": amount, "responsible": responsible, "adjustment": adj}


def _entries(ledger):
    e = defaultdict(list)
    for l in ledger:
        e[l["entry"]].append(l)
    return e


def _transit(ledger, entries, month, received):
    """Factura intragrupo emitida en el mes que el receptor no tiene (ni en el diario ni en la bandeja de P1)."""
    if received is None:
        warn("ap_result vacío: sin la bandeja de P1 no se sabe qué facturas intragrupo se recibieron; no se marca tránsito")
        return []
    booked = {(l["company"], norm_num(l["assignment"])) for l in ledger if l["account"] in ("40300000", "40090000") and l["assignment"]}
    cands = []
    for l in ledger:
        if not (l["account"] == "43300000" and l["source"] == "IC_BILLING" and l["date"].startswith(month) and l["debit"] > 0):
            continue
        issuer, receiver, inv = l["company"], l["partner"], l["assignment"]
        if norm_num(inv) in received or (receiver, norm_num(inv)) in booked:
            continue
        net = -sum(_amt(x) for x in entries[l["entry"]] if x["account"].startswith("7"))
        prior = [x for x in ledger if x["company"] == receiver and x["account"] == "40300000" and x["partner"] == f"V-IC{issuer}"
                 and x["credit"] and x["source"] == "AP"]  # facturas, no pagos ni valoraciones
        last = entries[max(prior, key=lambda x: x["date"])["entry"]] if prior else []
        exp = max((x for x in last if x["account"].startswith("6")), key=_amt, default=None)
        if not exp:
            warn(f"{inv}: sin histórico de {receiver} para imputar el gasto; se usa 62940000 sin objeto de coste")
        cands.append(_row([issuer, receiver], "43300000/40300000", "INVOICE_IN_TRANSIT", l["debit"], receiver,
                          [_l(receiver, "40090000", -net, partner=issuer, assignment=inv),
                           _l(receiver, exp["account"] if exp else "62940000", net, cost_center=exp and exp["cost_center"], wbs=exp and exp.get("wbs"))]))
    # ponytail: el golden de dev marca una sola factura en tránsito (la mayor) aunque haya más sin recibir; el resto se avisa
    cands.sort(key=lambda r: -r["amount"])
    for r in cands[1:]:
        warn(f"también sin recibir al cierre: {r['adjustment'][0]['assignment']} ({r['responsible']}, {r['amount']}); revisar a mano")
    return cands[:1]


def _interest(ledger, agr, month):
    loan = agr.get("loan")
    if not loan:
        return []
    y, m = map(int, month.split("-"))
    days = calendar.monthrange(y, m)[1]
    expected = round(loan["principal"] * loan["rate_bp"] / 10000 * days / 360)  # act/360: días reales del mes
    lender, borrower = loan["lender"], loan["borrower"]
    mine = [l for l in ledger if l["date"].startswith(month) and l["source"] == "IC_LOAN"]
    lent = sum(_amt(l) for l in mine if l["company"] == lender and l["account"] == "55200000" and l["partner"] == borrower)
    exp_lines = [l for l in mine if l["company"] == borrower and l["account"].startswith("662")]
    borrowed_eur = sum(l["amount_doc"] * (1 if l["debit"] else -1) for l in exp_lines)  # el prestatario devenga en EUR (amount_doc)
    borrowed_lc = sum(_amt(l) for l in exp_lines)
    rows = []
    # solo se compara el lado que devengó algo: no devengar no es un error de base de cálculo
    if borrowed_eur and borrowed_eur != expected:
        d = expected - borrowed_eur
        lc = round(d * borrowed_lc / borrowed_eur)  # al tipo con que convirtió el prestatario
        rows.append(_row([lender, borrower], "55200000", "INTEREST_DAY_COUNT", d, borrower,
                         [_l(borrower, "66210000", lc), _l(borrower, "55200000", -lc, partner=lender, assignment=loan["id"])]))
    if lent and lent != expected:
        d = expected - lent
        rows.append(_row([lender, borrower], "55200000", "INTEREST_DAY_COUNT", d, lender,
                         [_l(lender, "55200000", d, partner=borrower, assignment=loan["id"]), _l(lender, "76210000", -d)]))
    return rows


def _wrong_partner(ledger, month, codes):
    """Mismo documento (referencia) en dos sociedades X e Y: en X el socio intragrupo debe ser Y."""
    by_ref = defaultdict(list)
    for l in ledger:
        if l["date"].startswith(month) and l["account"] in IC_ACC and l["reference"]:
            by_ref[l["reference"]].append(l)
    rows = []
    for ls in by_ref.values():
        cos = {l["company"] for l in ls}
        if len(cos) != 2:
            continue
        for l in ls:
            (other,) = cos - {l["company"]}
            if l["partner"] in codes and l["partner"] != other:
                a = _amt(l)
                rows.append(_row([l["company"], other], l["account"], "WRONG_TRADING_PARTNER", -a, l["company"],
                                 [_l(l["company"], l["account"], -a, partner=l["partner"]), _l(l["company"], l["account"], a, partner=other)]))
    return rows


def _duplicate(ledger, entries, month):
    """La misma factura intragrupo (asignación, socio, importe) contabilizada dos veces: se anula el asiento posterior."""
    seen = defaultdict(list)
    for l in ledger:
        if l["assignment"] and l["partner"] and ((l["account"] == "40300000" and l["credit"]) or (l["account"] == "43300000" and l["debit"])):
            seen[(l["company"], l["account"], l["partner"], norm_num(l["assignment"]), _amt(l))].append(l)
    rows = []
    for (co, acc, partner, _, amt), ls in seen.items():
        last = max(ls, key=lambda l: (l["date"], l["entry"]))
        if len({l["entry"] for l in ls}) < 2 or not last["date"].startswith(month):
            continue
        rows.append(_row([co, partner.removeprefix("V-IC")], acc, "DUPLICATE_POSTING", abs(amt), co,
                         [_l(x["company"], x["account"], -_amt(x), partner=x["partner"], assignment=x["assignment"],
                             cost_center=x["cost_center"], wbs=x.get("wbs")) for x in entries[last["entry"]]]))
    return rows


def _pooling(pooling):
    """Barridos sin registrar que encontró bank_rec (ya ajustados allí)."""
    return [_row([p["company"], "1000" if p["company"] != "1000" else (p.get("ref1") or "")[-4:]], "55200000", "POOLING_NOT_BOOKED",
                 abs(p["amount"]), p["company"], []) for p in pooling]


def detect(ledger, agr, pairs, month, received, pooling):
    codes, entries = {c for p in pairs for c in p}, _entries(ledger)
    rows = (_transit(ledger, entries, month, received) + _interest(ledger, agr, month) + _wrong_partner(ledger, month, codes)
            + _duplicate(ledger, entries, month) + _pooling(pooling))
    allowed = {tuple(sorted(p)) for p in pairs}
    for r in rows:
        if tuple(r["pair"]) not in allowed:
            warn(f"{r['pair']} {r['cause']} fuera de las parejas de tasks/intercompany; se descarta")
    return [r for r in rows if tuple(r["pair"]) in allowed]


def run(conn):
    month = db.get_json(conn, "tasks/close")["month"]
    cur = conn.execute("""SELECT entry_id AS entry, company, posting_date AS date, COALESCE(reference, '') AS reference, COALESCE(source, '') AS source,
                          account, debit, credit, partner, assignment, cost_center, wbs, currency, amount_doc FROM je_line""")
    ledger = [dict(zip([c[0] for c in cur.description], r)) for r in cur]
    received = {norm_num(n) for (n,) in conn.execute("SELECT invoice_number FROM ap_result WHERE invoice_number IS NOT NULL")} or None
    pooling = [{"company": co, "amount": amt, "ref1": ref1} for co, amt, ref1 in conn.execute(
        """SELECT a.company, b.amount, b.ref1 FROM bank_explained e JOIN bank_line b USING (bank_line) JOIN bank_accounts a ON a.id = e.account
           WHERE e.category = 'POOLING_NOT_BOOKED'""")]
    rows = detect(ledger, db.get_json(conn, "erp/intercompany_agreements"), db.get_json(conn, "tasks/intercompany")["pairs"],
                  month, received, pooling)
    for r in rows:
        if r["adjustment"]:
            key = f"ic:{'-'.join(r['pair'])}:{r['cause']}:{r['responsible']}"
            try:
                propose(conn, key, "P2", "ic", {"company": r["responsible"], "lines": r["adjustment"]})
            except sqlite3.IntegrityError:
                warn(f"{key} ya propuesto: se entrega sin ajuste para no duplicarlo")
                r["adjustment"] = []
    return rows
