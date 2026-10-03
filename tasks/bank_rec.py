"""P2 · Conciliación bancaria (§4). El extracto es la fuente de verdad: cada línea del banco y cada línea 572 del mes
se explica exactamente una vez (casada, o sin casar con su categoría) y lo que falta en libros se ajusta.

`reconcile(accounts, ctx)` es puro (dicts → filas de bank_rec.jsonl); `run(conn)` carga datos, propone asientos y
rellena bank_explained (P3 lee de ahí los UNRECORDED_RECEIPT).
"""
import json
import re
import sys
import unicodedata
from collections import defaultdict
from datetime import date
from types import SimpleNamespace

from common import db, review
from common.je import make_je, norm_num, propose

WINDOW = 3  # días de desfase banco/libro admitidos (en dev siempre 0)
AFTER_THE_FACT = ("BANKFEE", "CARD", "DD", "INTEREST", "LOAN", "CLOSE_FX")  # registran a posteriori un cargo ya visto: no quedan pendientes
CARRY_DAYS = 10  # una partida abierta del mes anterior se busca hasta 10 días atrás
MAX_DIFF = 0.5  # una casación con diferencia no puede diferir más del 50 %

RULES = [  # (regex sobre texto + concepto del extracto, clase); el orden importa
    (r"ANULACI[OÓ]N (DE )?CARGO|CARGO DUPLICADO|RECTIFICACI[OÓ]N", "BANK_ERROR"),  # el banco corrige su propio error: sin ajuste
    (r"COMISI[OÓ]N DEVOLUCI[OÓ]N", "RETFEE"),
    (r"DEVOLUCI[OÓ]N RECIBO", "RET"),
    (r"CASH POOLING", "POOL"),
    (r"TARJETA", "CARD"),
    (r"INTERESES PR[EÉ]STAMO|LIQ INTERESES|CUOTA PR[EÉ]STAMO|INTERESES PROJECT", "LOAN"),
    (r"LIQUIDACI[OÓ]N INTERESES|RETENCI[OÓ]N .*INTERES", "INT"),
    (r"COMISI[OÓ]N|GASTOS|MANTENIMIENTO", "FEE"),
    (r"^RECIBO|MANDATO", "DD"),
    (r"^TRANSFERENCIA DE|^COBRO|^INGRESO|^ABONO TRANSFERENCIA", "RECEIPT"),  # abono de un tercero sin N43 importado
]
SIGNED = {"LOAN": -1, "RECEIPT": 1}  # reglas que solo valen con ese signo
CATEGORY = {"RETFEE": "RETURNED_DIRECT_DEBIT", "RET": "RETURNED_DIRECT_DEBIT", "POOL": "POOLING_NOT_BOOKED", "CARD": "CARD_SETTLEMENT_NOT_BOOKED",
            "LOAN": "LOAN_INTEREST_NOT_BOOKED", "INT": "INTEREST_NOT_BOOKED", "FEE": "BANK_FEE_NOT_BOOKED", "DD": "DIRECT_DEBIT_NOT_BOOKED",
            "RECEIPT": "UNRECORDED_RECEIPT", "BANK_ERROR": "BANK_ERROR"}
KIND = {"RETURNED_DIRECT_DEBIT": "RET", **{c: k for k, c in CATEGORY.items() if k not in ("RETFEE", "RET")}}  # categoría → clase


def warn(msg):
    print(f"[bank_rec] AVISO: {msg}", file=sys.stderr)


def _d(s):
    return date.fromisoformat(str(s)[:10])


def _n(s):
    return re.sub(r"[^0-9A-Z]", "", str(s or "").upper())


def _text(b):
    return f"{b['text']} {b.get('detail') or ''}".upper()


def _linked(b, k):
    """La referencia del libro aparece en el extracto, o una referencia del extracto en el libro."""
    refs = [_n(b.get("ref1")), _n(b.get("ref2"))]
    kr = _n(k["reference"])
    return (len(kr) >= 4 and kr in "|".join(refs + [_n(_text(b))])) or any(len(r) >= 6 and r in kr + "|" + _n(k["header"]) for r in refs)


STOP = {"TRANSFERENCIA", "TRANSF", "INTERNACIONAL", "EXTERIOR", "RECIBO", "ORDEN", "REMESA", "TRANSFERENCIAS", "BENEF", "ORDENANTE",
        "CAMBIO", "APLICADO", "LIMITADA", "UNIPESSOAL", "SOCIEDAD", "SERVICIOS", "SERVICOS"}


def _words(s):
    s = unicodedata.normalize("NFKD", str(s or "").upper()).encode("ascii", "ignore").decode()
    return set(re.findall(r"[A-Z]{5,}", s)) - STOP


def _name_linked(b, k):
    """Sin referencia común: el beneficiario/ordenante del extracto aparece en el texto del asiento."""
    return bool(_words(_text(b)) & _words(k["header"]))


def _gap(b, k):
    return abs((_d(b["booking_date"]) - _d(k["date"])).days)


def _key(line_id):
    e, _, n = line_id.partition("#")
    return e, int(n or 0)


def _same_sign(b, k):
    return (k["amount"] > 0) == (b["amount"] > 0)


def _l(account, amount, **kw):
    """Línea con importe con signo (debe > 0)."""
    return dict(account=account, debit=max(amount, 0), credit=max(-amount, 0), **kw)


def _group(items, key):
    g = defaultdict(list)
    for x in items:
        g[key(x)].append(x)
    return g


def _adj(out, a, category, ref, lines, bank_lines=()):
    je = make_je(a["company"], [dict(l, company=l.get("company") or a["company"]) for l in lines])  # valida cuadre
    out["adjustments"].append({"category": category, "ref": ref, "lines": je["lines"]})
    out["_explained"] = [x for x in out["_explained"] if x[0] not in bank_lines] + [(bl, "ADJ", category, ref) for bl in bank_lines]


# ---------------------------------------------------------------- casación
def _match(a, out):
    bank, book = a["bank"], [k for k in a["book"] if k["amount"] is not None]
    used_b, used_k = set(), set()
    free_b = lambda: [b for b in bank if b["bank_line"] not in used_b]
    free_k = lambda: [k for k in book if k["id"] not in used_k]

    def take(bs, ks):
        used_b.update(b["bank_line"] for b in bs)
        used_k.update(k["id"] for k in ks)
        out["matches"].append({"bank_lines": [b["bank_line"] for b in bs], "book_lines": sorted((k["id"] for k in ks), key=_key)})

    # 1) 1:1 importe exacto; primero con referencia enlazada, luego sin ella
    for need_link in (True, False):
        for b in free_b():
            c = [k for k in free_k() if k["amount"] == b["amount"] and _gap(b, k) <= WINDOW and (not need_link or _linked(b, k))]
            if c:
                take([b], [min(c, key=lambda k: (not _linked(b, k), _gap(b, k), _key(k["id"])))])
    # 2) 1:N remesa: líneas de libro enlazadas, o con la misma referencia, que suman el cargo
    for b in free_b():
        near = [k for k in free_k() if _gap(b, k) <= WINDOW and _same_sign(b, k)]
        groups = [[k for k in near if _linked(b, k)]] + [g for r, g in _group(near, lambda k: _n(k["reference"])).items() if r]
        g = next((g for g in groups if len(g) >= 2 and sum(k["amount"] for k in g) == b["amount"]), None)
        if g:
            take([b], g)
    # 3) N:1 lotes: líneas del banco con el mismo concepto (sin «LOTE n») contra un asiento
    for k in free_k():
        near = [b for b in free_b() if _gap(b, k) <= WINDOW]
        g = next((g for g in _group(near, lambda b: re.sub(r"\s*LOTE\s*\d+.*", "", b["text"])).values()
                  if len(g) >= 2 and sum(b["amount"] for b in g) == k["amount"]), None)
        if g:
            take(g, [k])
    # 3b) partida abierta del mes anterior (pago pendiente, traspaso en tránsito) que el banco liquida este mes:
    #     asiento del mes anterior sin línea igual en el extracto anterior
    prev_open = []
    if a.get("prev_book"):  # se concilia el mes anterior con las mismas pasadas: abierto = lo que allí quedó sin casar
        scratch = {"matches": [], "adjustments": [], "_explained": [], "unmatched_book": []}
        _, prev_used = _match(dict(a, bank=a["prev_bank"], book=a["prev_book"], prev_book=[]), scratch)
        prev_open = [k for k in a["prev_book"] if k["id"] not in prev_used and not k["source"].startswith(AFTER_THE_FACT)]
    for b in free_b():
        c = [k for k in prev_open if k["id"] not in used_k and k["amount"] == b["amount"] and _gap(b, k) <= CARRY_DAYS]
        if c:
            take([b], [min(c, key=lambda k: (not _linked(b, k), _gap(b, k)))])
    # 4) 1:1 con diferencia → se casa y se ajusta la diferencia. Enlace por referencia (diferencia ≤ 50 %) o, si no hay,
    #    por nombre del beneficiario con diferencia pequeña (≤ 1 %: dígitos traspuestos, céntimos)
    for b in free_b():
        c = [k for k in free_k() if _gap(b, k) <= WINDOW and _same_sign(b, k) and (
             (_linked(b, k) and abs(b["amount"] - k["amount"]) <= MAX_DIFF * abs(k["amount"]))
             or (_name_linked(b, k) and abs(b["amount"] - k["amount"]) <= 0.01 * abs(k["amount"])))]
        if c:
            k = min(c, key=lambda k: (_gap(b, k), abs(b["amount"] - k["amount"])))
            take([b], [k])
            _diff(a, b, k, out)
    return used_b, used_k


def _diff(a, b, k, out):
    d, gl, ref = b["amount"] - k["amount"], a["gl"], f"bankdiff:{b['bank_line']}"
    if a["currency"] != a["lc"]:
        return warn(f"{a['id']}: diferencia {d} {a['currency']} entre {b['bank_line']} y {k['id']}, sin ajuste")
    partner = next((l for l in k["lines"] if str(l["account"])[:2] in ("40", "41", "43") and l.get("partner")), None)
    if k["source"] == "SWIFT" or "TRANSF. EXTERIOR" in _text(b):
        # 668/768 según la diferencia realizada total: valor de la factura (línea del socio) frente a lo que movió el banco
        realized = partner["debit"] - partner["credit"] + b["amount"] if partner else d
        return _adj(out, a, "FX_RATE_DIFFERENCE", ref, [_l(gl, d), _l("76800000" if realized >= 0 else "66800000", -d)])
    if k["source"] == "LOAN" or "PRESTAMO" in _text(b):
        return _adj(out, a, "LOAN_INTEREST_NOT_BOOKED", ref, [_l(gl, d), _l("66200000", -d)])
    if partner:  # §4: categoría de libro; el cargo del banco queda casado con su asiento
        out["unmatched_book"].append({"book_line": k["id"], "category": "BOOK_AMOUNT_ERROR"})
        return _adj(out, a, "BOOK_AMOUNT_ERROR", ref,
                    [_l(gl, d), _l(partner["account"], -d, partner=partner["partner"], assignment=partner.get("assignment"))])
    warn(f"{a['id']}: diferencia {d} sin causa entre {b['bank_line']} y {k['id']}, sin ajuste")


def _factoring(a, out, ctx):
    """Anticipo de factoring abonado neto de intereses y comisión sin registrar el gasto: Dr 665 / Cr 553."""
    book = {k["id"]: k for k in a["book"] + a.get("prev_book", [])}
    for m in out["matches"]:
        ks = [book[i] for i in m["book_lines"]]
        fac = ctx.factoring.get(ks[0]["reference"])
        if ks[0]["source"] != "FACTORING" or not fac or any(str(l["account"]).startswith("665") for l in ks[0]["lines"]):
            continue
        if abs(sum(f["advance"] - f["interest"] - f["fee"] for f in fac) - sum(k["amount"] for k in ks)) > 2:
            continue  # liquidaciones y otros abonos: no es un anticipo neto
        for f in fac:
            ch = f["interest"] + f["fee"]
            _adj(out, a, "FACTORING_CHARGES_NOT_BOOKED", f"factfee:{f['invoice']}",
                 [_l("66500000", ch), _l("55300000", -ch, partner="FACTOR-BAE", assignment=f["invoice"])])


# ---------------------------------------------------------------- sin casar
def _to_lc(a, amount, day, ctx):
    if a["currency"] == a["lc"]:
        return amount
    return round(amount / ctx.rate(a["currency"], day) * ctx.rate(a["lc"], day))


def _kind(a, b, bs, seen, ctx):
    sig = (b["amount"], _n(b.get("ref1")), _n(b.get("ref2")), _n(b.get("detail")))
    dup = b["amount"] < 0 and (sig[1] or sig[2]) and seen.setdefault(sig, b) is not b
    if b not in bs:
        return None
    if dup:  # cargo repetido del banco: mismo importe y mismas referencias que uno anterior
        return "BANK_ERROR"
    t = _text(b)
    k = next((k for rx, k in RULES if re.search(rx, t) and SIGNED.get(k, 0) * b["amount"] >= 0), None)
    if k is None:  # sin regla: decide la IA con la evidencia; si no hay decisión segura, prudente (sin asiento) y queda como duda
        ev = {"account": a["id"], "company": a["company"], **{f: b.get(f) for f in ("booking_date", "amount", "text", "detail", "ref1", "ref2")},
              "prior_statement_same_amount": [{f: p.get(f) for f in ("booking_date", "amount", "text", "ref2")}
                                              for p in a["prev_bank"] if abs(p["amount"]) == abs(b["amount"])]}
        k = KIND[ctx.decide(f"bank:{b['bank_line']}", ev, sorted(KIND), "BANK_ERROR")]
    return k


def _classify_bank(a, bs, out, ctx):
    gl, co = a["gl"], a["company"]
    seen, kinds = {}, {}
    for b in a["bank"]:
        kinds[b["bank_line"]] = _kind(a, b, bs, seen, ctx)
    for b in bs:
        out["unmatched_bank"].append({"bank_line": b["bank_line"], "category": CATEGORY[kinds[b["bank_line"]]]})
        out["_explained"].append((b["bank_line"], "UNMATCHED", CATEGORY[kinds[b["bank_line"]]], None))
    by = _group(bs, lambda b: kinds[b["bank_line"]])
    lc = lambda b: _to_lc(a, b["amount"], b["booking_date"], ctx)
    post = lambda cat, g, lines: _adj(out, a, cat, f"bank:{g[0]['bank_line']}", lines, [b["bank_line"] for b in g])

    for g in _group(by["FEE"], lambda b: (b["booking_date"], b["text"], b["amount"])).values():
        amt = sum(lc(b) for b in g)
        post("BANK_FEE_NOT_BOOKED", g, [_l(gl, amt), _l("66900000" if re.search(r"\bAVAL", _text(g[0])) else "62600000", -amt)])
    for g in _group(by["INT"], lambda b: b["booking_date"]).values():
        gross, ret = sum(lc(b) for b in g if b["amount"] > 0), -sum(lc(b) for b in g if b["amount"] < 0)
        post("INTEREST_NOT_BOOKED", g, [_l(gl, gross - ret), _l("47300000", ret), _l("76200000", -gross)])
    for b in by["LOAN"]:
        post("LOAN_INTEREST_NOT_BOOKED", [b], [_l(gl, lc(b)), _l("66200000", -lc(b))])
    for b in by["CARD"]:
        post("CARD_SETTLEMENT_NOT_BOOKED", [b], [_l(gl, lc(b)), _l("62910000", -lc(b), cost_center=f"CC-{co}-DIR")])
    for b in by["RECEIPT"]:
        post("UNRECORDED_RECEIPT", [b], [_l(gl, lc(b)), _l("55500000", -lc(b))])
    for b in by["POOL"]:
        m = re.match(r"CP\d{6}(\d{4})$", b.get("ref1") or "")
        partner = "1000" if co != "1000" else (m and m.group(1))
        if not partner:
            warn(f"{a['id']} {b['bank_line']}: barrido sin sociedad participante en la referencia, sin socio")
        post("POOLING_NOT_BOOKED", [b], [_l(gl, lc(b)), _l("55200000", -lc(b), partner=partner)])
    fees = list(by["RETFEE"])
    for b in by["RET"]:
        fee = next((f for f in fees if f["booking_date"] == b["booking_date"]), None)
        if fee:
            fees.remove(fee)
        rc = (re.search(r"RC\d{2}-\d+", f"{b.get('ref2')} {_text(b)}") or [None])[0]
        cust = ctx.receipt_customer.get(rc)
        if not cust:
            warn(f"{a['id']} {b['bank_line']}: recibo devuelto {rc} sin cliente")
        fee_amt = -lc(fee) if fee else 0
        post("RETURNED_DIRECT_DEBIT", [b] + [fee] * bool(fee),
             [_l(gl, lc(b) - fee_amt), _l("43000000", -lc(b), partner=cust, assignment=rc)] + [_l("62600000", fee_amt)] * bool(fee))
    for f in fees:
        post("RETURNED_DIRECT_DEBIT", [f], [_l(gl, lc(f)), _l("62600000", -lc(f))])
    for b in by["DD"]:
        t = _text(b)
        v = (re.search(r"MANDATO\s+(V\d+)", t) or [None, None])[1]
        fra = b.get("ref2") or (re.search(r"FRA\s+(\S+)", t) or [None, None])[1]
        inv = v and fra and ctx.ap.get((co, v, norm_num(fra)))
        if inv:  # solo con la factura en POST y en esta sociedad; rechazada, no recibida o de otra sociedad: sin asiento (golden dev)
            post("DIRECT_DEBIT_NOT_BOOKED", [b], [_l(gl, lc(b)), _l(ctx.vendor_acc.get(v, "41000000"), -lc(b), partner=v, assignment=inv)])


def _classify_book(a, ks, matched, out, ctx):
    for k in ks:
        dup = any(o["id"] in matched and o["entry"] != k["entry"] and o["amount"] == k["amount"] and _n(o["reference"])
                  and _n(o["reference"]) == _n(k["reference"]) for o in a["book"])
        prev = [b for b in a["prev_bank"] if b["amount"] == k["amount"]]
        if k["source"].startswith("CLOSE_FX") or k["reference"].upper().startswith("FXV"):
            c = "FX_REVALUATION"
        elif dup and k["lines"]:
            c = "BOOK_DUPLICATE"
            _adj(out, a, c, f"book:{k['entry']}", [_l(l["account"], l["credit"] - l["debit"], partner=l.get("partner"), assignment=l.get("assignment"),
                                                       cost_center=l.get("cost_center"), wbs=l.get("wbs"), company=l.get("company")) for l in k["lines"]])
        elif any(_linked(b, k) for b in prev) or (len(prev) == 1 and _d(k["date"]).day <= 7):
            c = "PRIOR_PERIOD_BANK_ITEM"
        elif k["source"] == "TREASURY" or "TRASPASO" in k["header"].upper():
            c = "TRANSFER_IN_TRANSIT"
        elif k["amount"] is not None and k["amount"] < 0:
            c = "OUTSTANDING_PAYMENT"
        else:  # abono en libros que el banco no refleja y sin regla: decide la IA; prudente: tránsito (sin ajuste)
            c = ctx.decide(f"book:{k['id']}", {"account": a["id"], **{f: k[f] for f in ("date", "amount", "reference", "header", "source")}},
                           ["OUTSTANDING_PAYMENT", "TRANSFER_IN_TRANSIT", "PRIOR_PERIOD_BANK_ITEM", "FX_REVALUATION"], "TRANSFER_IN_TRANSIT")
        out["unmatched_book"].append({"book_line": k["id"], "category": c})


def _wrong_account(state):
    """Cargo sin libro en A y asiento sin banco en otra cuenta de la misma sociedad: se reclasifica una vez, en A."""
    for a, out, bs, _, _ in state:
        for b in list(bs):
            for a2, out2, _, ks2, _ in state:
                if a2 is a or a2["company"] != a["company"] or a2["currency"] != a["currency"]:
                    continue
                k = next((k for k in ks2 if k["amount"] == b["amount"] and _gap(b, k) <= WINDOW), None)
                if k:
                    bs.remove(b)
                    ks2.remove(k)
                    out["unmatched_bank"].append({"bank_line": b["bank_line"], "category": "WRONG_BANK_ACCOUNT"})
                    out2["unmatched_book"].append({"book_line": k["id"], "category": "WRONG_BANK_ACCOUNT"})
                    _adj(out, a, "WRONG_BANK_ACCOUNT", f"bank:{b['bank_line']}", [_l(a["gl"], b["amount"]), _l(a2["gl"], -b["amount"])],
                         [b["bank_line"]])
                    break


def reconcile(accounts, ctx):
    state = []
    for a in accounts:
        out = {"account": a["id"], "company": a["company"], "matches": [], "unmatched_bank": [], "unmatched_book": [], "adjustments": [],
               "_explained": []}
        used_b, used_k = _match(a, out)
        out["_explained"] += [(b, "MATCH", None, None) for m in out["matches"] for b in m["bank_lines"]]
        _factoring(a, out, ctx)
        state.append((a, out, [b for b in a["bank"] if b["bank_line"] not in used_b], [k for k in a["book"] if k["id"] not in used_k], used_k))
    _wrong_account(state)
    for a, out, bs, ks, used_k in state:
        _classify_bank(a, bs, out, ctx)
        _classify_book(a, ks, used_k, out, ctx)
    return [s[1] for s in state]


# ---------------------------------------------------------------- carga y registro
def _prev_month(m):
    y, mo = map(int, m.split("-"))
    return f"{y - (mo == 1)}-{12 if mo == 1 else mo - 1:02d}"


def _book(q, a, month):
    """Líneas 572 de la cuenta en el mes, con su asiento completo (para anular duplicados o ver el proveedor)."""
    out = []
    for r in q("""SELECT j.*, e.lines FROM je_line j JOIN (SELECT entry_id, json_group_array(json_object('company', company, 'account', account,
                  'debit', debit, 'credit', credit, 'partner', partner, 'assignment', assignment, 'cost_center', cost_center, 'wbs', wbs)) lines
                  FROM je_line WHERE posting_date LIKE ? GROUP BY entry_id) e USING (entry_id)
                  WHERE j.company = ? AND j.account = ? AND j.posting_date LIKE ? ORDER BY j.entry_id, j.line""",
               month + "%", a["company"], a["gl"], month + "%"):
        sign = 1 if r["debit"] else -1  # cuenta en divisa (USD de 3100): se casa por el importe en divisa
        amt = r["debit"] - r["credit"] if a["currency"] == a["lc"] else (sign * r["amount_doc"] if r["currency"] == a["currency"] else None)
        out.append({"id": r["line_id"], "entry": r["entry_id"], "date": r["posting_date"], "amount": amt, "reference": r["reference"] or "",
                    "header": r["header_text"] or "", "source": r["source"] or "", "lines": json.loads(r["lines"])})
    return out


def load(conn):
    month = db.get_json(conn, "tasks/close")["month"]

    def q(sql, *p):
        cur = conn.execute(sql, p)
        return [dict(zip([c[0] for c in cur.description], r)) for r in cur]

    lc = {r["code"]: r["currency"] for r in q("SELECT code, currency FROM companies")}
    bank = _group(q("SELECT * FROM bank_line WHERE month IN (?, ?) ORDER BY rowid", month, _prev_month(month)), lambda b: (b["account"], b["month"]))
    accounts = []
    for ba in q("SELECT b.* FROM task_bank_accounts t JOIN bank_accounts b ON b.id = t.id ORDER BY t.rowid"):
        a = {"id": ba["id"], "company": ba["company"], "gl": ba["gl_account"], "currency": ba["currency"], "lc": lc.get(ba["company"], "EUR"),
             "bank": bank[(ba["id"], month)], "prev_bank": bank[(ba["id"], _prev_month(month))]}
        a["book"], a["prev_book"] = _book(q, a, month), _book(q, a, _prev_month(month))
        accounts.append(a)

    ap = {(r["company"], r["vendor"], norm_num(r["number"])): r["number"]
          for r in q("SELECT company, vendor, number FROM ap_invoices WHERE decision IN ('POST', 'POST_PAYMENT_BLOCK')")}
    ap |= {(r["company"], r["vendor_id"], norm_num(r["invoice_number"])): r["invoice_number"]
           for r in q("SELECT company, vendor_id, invoice_number FROM ap_result WHERE decision IN ('POST', 'POST_PAYMENT_BLOCK') AND invoice_number IS NOT NULL")}
    return accounts, SimpleNamespace(
        ap=ap, rate=lambda cur, day: db.fx_rate(conn, cur, day), decide=lambda key, ev, opts, fb: review.decide(conn, key, "bank_rec", ev, opts, fb),
        vendor_acc={r["id"]: r["reconciliation_account"] for r in q("SELECT id, reconciliation_account FROM vendors")},
        receipt_customer={r["id"]: r["customer"] for r in q("SELECT id, customer FROM ar_invoices")},
        factoring=_group(q("SELECT * FROM factoring_assignments"), lambda f: f["remittance"]))


def residuals(conn, rows):
    """Por cuenta en moneda local: saldo final del extracto − (572 al cierre + ajustes − libro abierto + banco sin ajuste). Debe ser 0."""
    month = db.get_json(conn, "tasks/close")["month"]
    one = lambda sql, *p: conn.execute(sql, p).fetchone()[0] or 0
    adj = defaultdict(int)
    for r in rows:
        for a in r["adjustments"]:
            for l in a["lines"]:
                adj[(l["company"], l["account"])] += l["debit"] - l["credit"]
    out = {}
    for r in rows:
        co, gl, cur = conn.execute("SELECT company, gl_account, currency FROM bank_accounts WHERE id = ?", (r["account"],)).fetchone()
        if cur != one("SELECT currency FROM companies WHERE code = ?", co):
            continue  # cuenta en divisa con libro en moneda local: no comparable céntimo a céntimo
        book_open = sum(one("SELECT debit - credit FROM je_line WHERE line_id = ?", x["book_line"]) for x in r["unmatched_book"]
                        if x["category"] in ("OUTSTANDING_PAYMENT", "TRANSFER_IN_TRANSIT", "FX_REVALUATION"))
        bank_open = sum(one("SELECT amount FROM bank_line WHERE bank_line = ?", x["bank_line"]) for x in r["unmatched_bank"]
                        if one("SELECT kind = 'ADJ' FROM bank_explained WHERE bank_line = ?", x["bank_line"]) == 0)
        gl_end = one("SELECT SUM(debit - credit) FROM je_line WHERE company = ? AND account = ? AND posting_date <= ?", co, gl, month + "-31")
        closing = one("SELECT closing FROM bank_statement WHERE account = ? AND month = ?", r["account"], month)
        out[r["account"]] = closing - (gl_end + adj[(co, gl)] - book_open + bank_open)
    return out


def run(conn):
    accounts, ctx = load(conn)
    rows = reconcile(accounts, ctx)
    for r in rows:
        for adj in r["adjustments"]:
            propose(conn, adj["ref"], "P2", "bank_rec", {"company": r["company"], "lines": adj["lines"]})
        conn.executemany("INSERT INTO bank_explained VALUES (?, ?, ?, ?, 'P2', ?)",
                         [(bl, r["account"], kind, cat, ref) for bl, kind, cat, ref in r.pop("_explained")])
    for account, diff in residuals(conn, rows).items():
        if diff:
            warn(f"{account}: el libro conciliado no cuadra con el saldo final del extracto por {diff} céntimos; falta una pieza")
    return rows
