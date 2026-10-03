"""P3 — aplicación de cobros: una fila de ar_cash.jsonl por bank_line de tasks/ar_receipts.json.

Escalera: pagaré → remesa/FACe → cobro de factura cedida → importe exacto (1 o 2-3 facturas) → penalidad →
duplicado → compensación con AP → pago parcial (FIFO) → no cliente. Los cobros se procesan por fecha y cada uno
consume saldo, así que un segundo pago del mismo importe se detecta como duplicado."""
import csv
import itertools
import json
import re
import sys
import unicodedata
from collections import defaultdict
from datetime import date

from common import db
from common.je import make_je, propose
from tasks import ar_billing
from tasks.ar_billing import cents, pdf_lines, q

STOP = {"DE", "DEL", "LA", "EL", "LOS", "LAS", "TRANSFERENCIA"}
NON_CUSTOMER = [(r"IVA|TRIBUTAR|HACIENDA|AEAT", "47000000"), (r"SEGUR|INDEMNIZ|MAPFRE", "75900000")]  # resto: devolución de fianza
FIANZA = "56500000"


def warn(b, msg):
    print(f"AVISO ar_cash {b['bank_line']}: regla de respaldo — {msg}", file=sys.stderr)


def words(s):
    s = unicodedata.normalize("NFD", s.upper()).encode("ascii", "ignore").decode()
    return [w for w in re.sub(r"[^A-Z0-9 ]", " ", s).split() if w not in STOP and len(w) > 2]


def name_score(text, name):
    t, n = words(text), words(name)
    return sum(any(x.startswith(w) for x in n) for w in t) / len(t) if t else 0


def remittances(root, bank):
    """Evidencia de pago por (fecha, importe): avisos de pago en PDF y estados FACe. → {(fecha ISO, importe): [(factura, importe)]}"""
    out = {}
    for f in (root / "inbox/ar/remittances").glob("aviso_pago_*.pdf"):
        t = pdf_lines(f)
        txt = " ".join(t)
        d, m, y = re.search(r"Fecha valor: (\d\d)/(\d\d)/(\d{4})", txt).groups()
        total = cents(re.search(r"total transferido: ([\d.]+,\d\d)", txt).group(1))
        out[(f"{y}-{m}-{d}", total)] = [(t[i - 1], cents(x)) for i, x in enumerate(t) if re.fullmatch(r"[\d.]+,\d\d EUR", x) and ":" not in t[i - 1]]
    for f in (root / "inbox/ar/remittances").glob("FACe_*.csv"):
        by_day = defaultdict(list)
        for r in csv.DictReader(open(f, encoding="utf-8"), delimiter=";"):
            if r["estado"] == "PAGADA":
                d, m, y = r["fecha_estado"].split("/")
                by_day[f"{y}-{m}-{d}"].append((r["numero_factura"], cents(r["importe_pagado"])))
        for day, rows in by_day.items():
            out[(day, None)] = rows  # el importe del banco puede ser menor (penalidad): se casa por fecha y cliente
    return out


class Cash:
    def __init__(self, conn):
        self.conn = conn
        self.root = db.phase_dir(conn)
        self.cust = {r["id"]: r["name"] for r in q(conn, "SELECT id, name FROM customers")}
        self.company = {r["id"]: r["company"] for r in q(conn, "SELECT id, company FROM bank_accounts")}
        due = {r["id"]: r["due_date"] for r in q(conn, "SELECT id, due_date FROM ar_invoices")}
        for b in ar_billing.billing_rows(conn):
            if b["expected"] == "INVOICE":
                due[b["journal_entry"]["lines"][0]["assignment"]] = b["invoice"]["due_date"]
        self.inv = {}  # factura → company, cliente, saldo, cargo original, vencimiento
        for r in q(conn, """SELECT company, partner, assignment, SUM(debit - credit) bal, SUM(debit) charged FROM ledger
                            WHERE account = '43000000' AND assignment IS NOT NULL GROUP BY 1, 2, 3"""):
            self.inv[r["assignment"]] = dict(company=r["company"], customer=r["partner"], bal=r["bal"], charged=r["charged"], due=due.get(r["assignment"]) or "9999-12-31")
        self.notes = {f"PAG{n['number']}": n for n in q(conn, "SELECT number, customer, maturity, amount FROM promissory_notes")}
        self.pag_open = {r["assignment"]: r["bal"] for r in q(conn, "SELECT assignment, SUM(debit - credit) bal FROM ledger WHERE account = '43100000' GROUP BY 1")}
        self.factored = {r["invoice"]: r["customer"] for r in q(conn, "SELECT invoice, customer FROM factoring_assignments")}
        self.penalty = {r["invoice"]: r["amount"] for r in q(conn, "SELECT invoice, amount FROM penalty_notices")}
        self.twin = {r["name"].lower(): r["id"] for r in q(conn, "SELECT id, name FROM vendors")}
        self.rem = remittances(self.root, None)
        self.paid = []  # cobros ya aplicados en esta ejecución: (cliente, importe, fecha, factura)

    def open(self, company, customer):
        return sorted((i for i, v in self.inv.items() if v["company"] == company and v["customer"] == customer and v["bal"] > 0), key=lambda i: (self.inv[i]["due"], i))

    def nearest(self, ops, day, need):
        """Un pago parcial va a la factura ya vencida más reciente (la que toca cobrar), no a saldos viejos residuales ni a facturas aún no vencidas."""
        ok = [i for i in ops if self.inv[i]["bal"] >= need]
        return min(ok, key=lambda i: (self.inv[i]["due"] > day, abs((date.fromisoformat(self.inv[i]["due"]) - date.fromisoformat(day)).days), i)) if ok else None

    def customers(self, company, text):
        """Clientes con facturas en la sociedad, ordenados por parecido del nombre con el texto del banco."""
        cs = {v["customer"] for v in self.inv.values() if v["company"] == company}
        return sorted(((name_score(text, self.cust.get(c, "")), c) for c in cs), key=lambda x: (-x[0], x[1]))

    def decide(self, b, company):
        amt, text = b["amount"], b["text"]
        scored = self.customers(company, text)
        best = [c for s, c in scored if s >= 0.5]
        # 0. pagaré al vencimiento
        for key, n in self.notes.items():
            if n["maturity"] == b["booking_date"] and n["amount"] == amt and self.pag_open.get(key):
                return n["customer"], [("pagare", n["number"], amt)], []
        # 1. aviso de pago o estado FACe con las facturas
        ev = self.rem.get((b["booking_date"], amt))
        if ev is None:
            day = self.rem.get((b["booking_date"], None)) or []
            cust = {self.inv[i]["customer"] for i, _ in day if i in self.inv}
            if day and cust & set(best) or day and sum(a for _, a in day) == amt:
                ev = day
        if ev:
            apps = [("invoice", i, a) for i, a in ev if i in self.inv]
            gap = sum(a for _, _, a in apps) - amt
            pen = [("PENALTY", i, self.penalty[i]) for _, i, _ in apps if i in self.penalty and self.penalty[i] == gap]
            if apps and (gap == 0 or pen):
                return self.inv[apps[0][1]]["customer"], apps, pen
        # 1b. mismo cliente y mismo importe que un cobro de la última semana: pagó dos veces
        for c, a, d, i in reversed(self.paid):
            if a == amt and 0 < (date.fromisoformat(b["booking_date"]) - date.fromisoformat(d)).days <= 7 and name_score(text, self.cust.get(c, "")) >= 0.5:
                warn(b, "mismo cliente e importe que un cobro de la última semana → duplicado")
                return c, [], [("OVERPAYMENT_DUPLICATE", i, amt)]
        # 2. factura cedida al factor, pagada por error al grupo
        for i, c in self.factored.items():
            if self.inv.get(i, {}).get("charged") == amt and self.inv[i]["company"] == company and self.inv[i]["bal"] <= 0:
                return c, [], [("FACTORED_MISDIRECTED", i, amt)]
        # 3. importe exacto: una factura (cualquier cliente) o 2-3 del cliente por nombre
        exact = [(-dict((c, s) for s, c in scored).get(self.inv[i]["customer"], 0), self.inv[i]["due"], i) for i in self.inv
                 if self.inv[i]["company"] == company and self.inv[i]["bal"] == amt]
        if exact:
            i = min(exact)[2]
            return self.inv[i]["customer"], [("invoice", i, amt)], []
        for c in best:
            ops = self.open(company, c)
            for n in (2, 3):
                for combo in itertools.combinations(ops, n):
                    if sum(self.inv[i]["bal"] for i in combo) == amt:
                        return c, [("invoice", i, self.inv[i]["bal"]) for i in combo], []
            # 4. penalidad notificada: lo cobrado + penalidad = suma de facturas
            for n in (1, 2, 3):
                for combo in itertools.combinations(ops, n):
                    for i in combo:
                        if i in self.penalty and sum(self.inv[j]["bal"] for j in combo) - self.penalty[i] == amt:
                            return c, [("invoice", j, self.inv[j]["bal"]) for j in combo], [("PENALTY", i, self.penalty[i])]
        if best:
            c = best[0]
            # 5. duplicado: ya se pagó una factura de ese importe
            dup = [i for i, v in self.inv.items() if v["customer"] == c and v["company"] == company and v["charged"] == amt and v["bal"] <= 0]
            if dup:
                warn(b, "importe de una factura ya cobrada → duplicado")
                return c, [], [("OVERPAYMENT_DUPLICATE", max(dup, key=lambda i: self.inv[i]["due"]), amt)]
            # 6. compensación con una factura de honorarios del propio cliente (AP abierta del mismo nombre)
            v = self.twin.get(self.cust[c].lower())
            ap = q(self.conn, """SELECT account, assignment, -SUM(debit - credit) bal FROM ledger WHERE partner = ? AND account IN ('40000000', '41000000')
                                 GROUP BY 1, 2 HAVING SUM(debit - credit) < 0 ORDER BY 2""", v) if v else []
            ops = self.open(company, c)
            tgt = ap and self.nearest(ops, b["booking_date"], amt + ap[0]["bal"])
            if tgt:
                a = ap[0]
                return c, [("invoice", tgt, amt + a["bal"])], [("NETTING_AP", a["assignment"], a["bal"], a["account"], v)]
            # 7. paga menos sin causa conocida: aplicación parcial a la factura que vence más cerca
            tgt = self.nearest(ops, b["booking_date"], amt + 1)
            if tgt:
                warn(b, f"pago parcial sin causa conocida → {tgt}")
                return c, [("invoice", tgt, amt)], []
            apps, left = [], amt
            for i in ops:
                if left <= 0:
                    break
                apps.append(("invoice", i, min(left, self.inv[i]["bal"])))
                left -= apps[-1][2]
            if apps and left == 0:
                warn(b, "pago parcial repartido FIFO")
                return c, apps, []
        # 8. no es cliente
        acc = next((a for rx, a in NON_CUSTOMER if re.search(rx, text.upper())), None)
        if acc is None:
            warn(b, "no cliente sin pista en el texto → devolución de fianza")
            acc = FIANZA
        return None, [], [("NON_CUSTOMER", None, amt, acc)]

    def row(self, b, company, customer, apps, res):
        lines = [dict(company=company, account="55500000", debit=b["amount"])]
        out_apps, out_res = [], []
        for kind, ref, a in apps:
            out_apps.append({kind: ref, "amount": a})
            acct, assign = ("43100000", f"PAG{ref}") if kind == "pagare" else ("43000000", ref)
            lines.append(dict(company=company, account=acct, credit=a, partner=customer, assignment=assign))
        for r in res:
            typ, ref, a, *extra = r
            acc = {"PENALTY": "70590000", "OVERPAYMENT_DUPLICATE": "43800000", "FACTORED_MISDIRECTED": "55300000"}.get(typ) or extra[0]
            out_res.append(dict(type=typ, amount=a, account=acc, **({"invoice": ref} if ref else {})))
            if typ == "PENALTY":
                lines.append(dict(company=company, account=acc, debit=a))
            elif typ == "NETTING_AP":
                lines.append(dict(company=company, account=acc, debit=a, partner=extra[1], assignment=ref))
            else:
                lines.append(dict(company=company, account=acc, credit=a, partner={"OVERPAYMENT_DUPLICATE": customer, "FACTORED_MISDIRECTED": "FACTOR-BAE"}.get(typ),
                                  assignment=ref if typ == "FACTORED_MISDIRECTED" else None))
        je = make_je(company, lines)
        return dict(bank_line=b["bank_line"], customer=customer, applications=out_apps, residuals=out_res, adjustment=je["lines"]), je

    def consume(self, apps, customer, b):
        if apps and customer:
            self.paid.append((customer, b["amount"], b["booking_date"], apps[0][1]))
        for kind, ref, a in apps:
            if kind == "invoice":
                self.inv[ref]["bal"] -= a
            else:
                self.pag_open[f"PAG{ref}"] = 0


def run(conn):
    cash = Cash(conn)
    lines = q(conn, f"SELECT b.* FROM bank_line b JOIN task_ar_receipts t ON t.id = b.bank_line ORDER BY b.booking_date, b.bank_line")
    rows = []
    for b in lines:
        company = cash.company[b["account"]]
        customer, apps, res = cash.decide(b, company)
        row, je = cash.row(b, company, customer, apps, res)
        propose(conn, f"arcash:{b['bank_line']}", "P3", "ar_cash", je)
        cash.consume(apps, customer, b)
        rows.append(row)
    return rows
