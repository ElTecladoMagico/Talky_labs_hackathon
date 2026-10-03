"""P3 — facturación AR: una fila de ar_billing.jsonl por billing_item de tasks/ar_billing_items.json."""
import base64
import calendar
import json
import re
import zlib
from datetime import date, timedelta

from common import db
from common.je import make_je, propose

OBRA_ACCOUNT = "70510000"


def pdf_lines(path):
    """Texto de un PDF de ReportLab (ASCII85 + Flate) como lista de líneas; sin dependencias."""
    out = []
    for m in re.finditer(rb"stream\r?\n(.*?)endstream", open(path, "rb").read(), re.S):
        s = m.group(1).strip()
        if not s.endswith(b"~>"):  # solo los streams de contenido (ASCII85); fuentes e imágenes son binarios
            continue
        s = zlib.decompress(base64.a85decode(s[:-2])).decode("latin1")
        for a, b in re.findall(r"\[(.*?)\]\s*TJ|\((.*?)(?<!\\)\)\s*Tj", s):
            t = "".join(re.findall(r"\((.*?)(?<!\\)\)", a)) if a else b
            out.append(re.sub(r"\\(\d{3}|.)", lambda m: chr(int(m.group(1), 8)) if len(m.group(1)) == 3 else m.group(1), t))
    return out


def cents(s):
    return int(re.sub(r"\D", "", s))  # "8.596.118,68" → 859611868


def pct(base, bp):
    return (base * bp + 5000) // 10000  # redondeo half-up; bp = puntos básicos


def q(conn, sql, *args):
    cur = conn.execute(sql, args)
    return [dict(zip([d[0] for d in cur.description], r)) for r in cur]


def certification(path):
    """Datos de una certificación de obra desde su PDF: aprobada, a origen, anterior, líneas (capítulo, descripción, importe)."""
    t = pdf_lines(path)
    txt = "\n".join(t)
    money = lambda label: cents(re.search(label + r"[^\d\n]*([\d.]+,\d\d)", txt).group(1))
    lines = [(l, t[i + 1], cents(t[i + 2])) for i, l in enumerate(t) if re.fullmatch(r"\d\d", l)]
    return dict(approved="CONFORME" in t, origin=money("a origen"), previous=money("anterior"), lines=lines,
                currency=re.search(r"\d,\d\d (EUR|MXN)", txt).group(1))


def next_number(conn, ctx, company, contract, day):
    """Siguiente nº de factura de la serie del contrato (prefijo de su última factura, con el año cambiado).
    Arranca tras la última factura anterior al mes: los huecos del mes en curso son los nuestros."""
    last = q(conn, "SELECT id FROM ar_invoices WHERE contract = ? ORDER BY date DESC, rowid DESC LIMIT 1", contract) \
        or q(conn, "SELECT id FROM ar_invoices WHERE company = ? ORDER BY date DESC, rowid DESC LIMIT 1", company)
    prefix = re.sub(r"\d+$", "", last[0]["id"])
    prefix = re.sub(r"(?<=\D)(\d{4}|\d{2})-$", lambda m: f"{day.year}-" if len(m.group(1)) == 4 else f"{day.year % 100:02d}-", prefix)
    if prefix not in ctx["seq"]:
        ctx["seq"][prefix] = max([int(i[len(prefix):]) for (i,) in conn.execute("SELECT id FROM ar_invoices WHERE id LIKE ? AND date < ?", (prefix + "%", day.isoformat()[:8] + "01"))
                                  if i[len(prefix):].isdigit()] or [0])
    ctx["seq"][prefix] += 1
    return f"{prefix}{ctx['seq'][prefix]:05d}"


def advance_left(conn, contract):
    """Anticipo pendiente de amortizar: facturas ANT del contrato − amortizaciones ya aplicadas."""
    adv = sum(r["gross"] for r in q(conn, "SELECT gross FROM ar_invoices WHERE contract = ? AND id LIKE 'ANT-%'", contract))
    used = sum(d["amount"] for r in q(conn, "SELECT deductions FROM ar_invoices WHERE contract = ?", contract)
               for d in json.loads(r["deductions"] or "[]") if d["code"] == "ADV_AMORT")
    return adv - used


def invoice(conn, ctx, item, day, parts):
    """Factura + asiento. parts = [(descripción, importe, cuenta de ingreso, {"wbs"|"cost_center": …})]; IVA, retención y deducciones salen del contrato."""
    c = ctx["contracts"][item["contract"]]
    cust = ctx["customers"][item["customer"]]
    net = sum(x[1] for x in parts)
    code = c["tax"]
    rate = ctx["tax"][code]["rate"] if ctx["tax"][code]["kind"] == "output" else 0
    tax = pct(net, rate)
    ret = pct(net, c.get("retention_bp") or 0)
    ded = []
    if c.get("mx5mill"):
        ded.append(dict(code="MX5MILL", amount=pct(net, 50), account="63100000"))
    if c.get("advance_bp"):
        ded.append(dict(code="ADV_AMORT", amount=min(pct(net + tax, c["advance_bp"]), advance_left(conn, c["id"])), account="43800000"))
    payable = net + tax - ret - sum(d["amount"] for d in ded)
    num = next_number(conn, ctx, item["company"], item["contract"], day)
    p = cust["id"]
    lines = [dict(account="43000000", debit=payable, partner=p, assignment=num), dict(account="43000900", debit=ret, partner=p, assignment=num)]
    lines += [dict(account=d["account"], debit=d["amount"], partner=p if d["account"] == "43800000" else None) for d in ded]
    lines.append(dict(account="47700000", credit=tax, tax_code=code))
    lines += [dict(account=acc, credit=max(amt, 0), debit=max(-amt, 0), tax_code=code, text=desc, **dim) for desc, amt, acc, dim in parts]  # importe negativo (desvíos) = al debe
    inv = dict(date=day.isoformat(), due_date=(day + timedelta(days=c["terms_days"])).isoformat(), tax_code=code, net=net, tax=tax,
               gross=net + tax, retention=ret, deductions=ded, payable=payable, currency=cust["currency"],
               lines=[dict(description=d, amount=a, account=acc, cost_center=dim.get("cost_center"), wbs=dim.get("wbs")) for d, a, acc, dim in parts])
    if cust["kind"] == "public" and cust["country"] == "ES":
        inv["face"] = json.loads(cust["dir3"])
    return dict(billing_item=item["billing_item"], type=item["type"], company=item["company"], customer=p, contract=c["id"],
                expected="INVOICE", invoice=inv, journal_entry=make_je(item["company"], [l for l in lines if l.get("debit") or l.get("credit")]))


def month_end(month):
    y, m = map(int, month.split("-"))
    return date(y, m, calendar.monthrange(y, m)[1])


def obra(conn, ctx, item):
    c = ctx["contracts"][item["contract"]]
    cert = certification(ctx["root"] / "inbox/ar/billing" / item["billing_item"] / item["documents"][0])
    if not cert["approved"]:
        return dict(billing_item=item["billing_item"], type=item["type"], company=item["company"], customer=item["customer"],
                    contract=item["contract"], expected="SKIP_PENDING_APPROVAL")
    net = cert["origin"] - cert["previous"]  # esta certificación = a origen − anterior
    caps = [[cap, desc, amt] for cap, desc, amt in cert["lines"]]
    caps[max(range(len(caps)), key=lambda i: caps[i][2])][2] += net - sum(x[2] for x in caps)  # ponytail: el descuadre de redondeo va al capítulo mayor
    return invoice(conn, ctx, item, month_end(item["month"]),
                   [(desc, amt, OBRA_ACCOUNT, {"wbs": f"{c['project']}.{cap}"}) for cap, desc, amt in caps])


def service_pdf(path):
    """Filas (concepto, orden, importe, conforme) de la tabla del parte mensual."""
    t = pdf_lines(path)
    return [(t[i - 2], t[i - 1], cents(x), t[i + 1].startswith("Conforme")) for i, x in enumerate(t) if re.fullmatch(r"[\d.]+,\d\d [A-Z]{3}", x)]


def service(conn, ctx, item):
    """Canon mensual + servicios extraordinarios solo con conformidad del técnico municipal."""
    c = ctx["contracts"][item["contract"]]
    parts = [(f"{c['name']} – {'canon mensual' if conc.startswith('Canon') else conc} {item['month']}", amt, "70500000", {"cost_center": c["cc"]})
             for conc, _, amt, ok in service_pdf(ctx["root"] / "inbox/ar/billing" / item["billing_item"] / item["documents"][0]) if ok]
    return invoice(conn, ctx, item, month_end(item["month"]), parts)


def revision(conn, ctx, item):
    """Decreto de revisión de precios: una línea por mes desde la fecha de efectos con (canon nuevo − anterior). Se factura 3 días tras la aprobación."""
    c = ctx["contracts"][item["contract"]]
    txt = " ".join(pdf_lines(ctx["root"] / "inbox/ar/billing" / item["billing_item"] / item["documents"][0]))
    new, old = (cents(x) for x in re.search(r"canon mensual en ([\d.]+,\d\d) EUR \(anterior: ([\d.]+,\d\d) EUR\)", txt).groups())
    months = re.findall(r"\d{4}-\d\d", re.search(r"fecha de efectos \(([^)]*)\)", txt).group(1))
    approved = date.fromisoformat(re.search(r"aprobaci.n: (\d{4}-\d\d-\d\d)", txt).group(1))
    return invoice(conn, ctx, item, approved + timedelta(days=3),
                   [(f"Revisión de precios – {c['name']} – diferencia {mo}", new - old, "70520000", {"cost_center": c["cc"]}) for mo in months])


def billing_day(month, day):
    """El día `day` del mes, pasado al siguiente día laborable. ponytail: solo fines de semana; si hace falta, sumar festivos (el histórico salta el Viernes Santo)."""
    d = date(*map(int, month.split("-")), day)
    return d + timedelta(days=max(0, 7 - d.weekday()) if d.weekday() > 4 else 0)


def signed(s):
    return -cents(s) if s.startswith("-") else cents(s)


def ppa(conn, ctx, item):
    """MWh medidos × % del PPA (truncado a milésimas) × precio fijo (truncado al céntimo), en la primera planta del contrato."""
    c = ctx["contracts"][item["contract"]]
    t = pdf_lines(ctx["root"] / "inbox/ar/billing" / item["billing_item"] / item["documents"][0])
    period = re.search(r"Periodo: (\d{4})-(\d\d)", " ".join(t)).groups()
    milli = sum(cents(x) for x in t if re.fullmatch(r"\d{1,3}(?:\.\d{3})*,\d{3}", x)) * c["share_bp"] // 10000
    net = milli * c["price_mwh"] // 1000
    desc = f"Energía suministrada PPA {period[1]}/{period[0]}: {milli / 1000:.3f} MWh × {c['price_mwh'] / 100:.2f} €/MWh"
    return invoice(conn, ctx, item, billing_day(item["month"], 3), [(desc, net, "70530000", {"cost_center": json.loads(c["plants"])[0]})])


def market(conn, ctx, item):
    """Liquidación del representante por planta menos desvíos (cc de administración)."""
    c = ctx["contracts"][item["contract"]]
    t = pdf_lines(ctx["root"] / "inbox/ar/billing" / item["billing_item"] / item["documents"][0])
    period = re.search(r"Periodo (\d{4})-(\d\d)", " ".join(t)).groups()
    rows = [(t[i - 2], cents(x)) for i, x in enumerate(t) if re.fullmatch(r"[\d.]+,\d\d EUR", x)]
    parts = [(f"Venta de energía en mercado {period[1]}/{period[0]} – {name}", amt, "70530000", {"cost_center": cc})
             for (name, amt), cc in zip(rows, json.loads(c["plants"]))]
    dev = signed(re.search(r"desv.os imputado: (-?[\d.]+,\d\d)", " ".join(t)).group(1))
    if dev:
        parts.append((f"Coste de desvíos {period[1]}/{period[0]}", dev, "70530000", {"cost_center": f"CC-{item['company']}-ADM"}))
    return invoice(conn, ctx, item, billing_day(item["month"], 6), parts)


HANDLERS = {"OBRA_CERTIFICATION": obra, "SERVICE_MONTHLY": service, "PRICE_REVISION": revision, "PPA": ppa, "MARKET_SETTLEMENT": market}


def billing_rows(conn):
    """Filas de entrega, sin efectos. close.py la reutiliza para las SKIP_PENDING_APPROVAL (obra pendiente de certificar)."""
    ctx = dict(root=db.phase_dir(conn), seq={}, tax=db.get_json(conn, "erp/tax_codes")["tax_codes"],
               contracts={r["id"]: r for r in q(conn, "SELECT * FROM sales_contracts")},
               customers={r["id"]: r for r in q(conn, "SELECT * FROM customers")})
    rows = []
    for (bid,) in conn.execute("SELECT id FROM task_ar_billing_items ORDER BY rowid").fetchall():
        item = json.loads((ctx["root"] / "inbox/ar/billing" / bid / "item.json").read_text())
        if item["type"] in HANDLERS:
            rows.append(HANDLERS[item["type"]](conn, ctx, item))
    return rows


def run(conn):
    rows = billing_rows(conn)
    for r in rows:
        if r["expected"] == "INVOICE":
            propose(conn, f"ar:{r['billing_item']}", "P3", "ar_billing", r["journal_entry"])
    return rows
