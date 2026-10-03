"""Extractos bancarios originales (N43, camt.053, CSV México): saldos, referencias y concepto completo.

lines.jsonl solo trae importe y un texto truncado; el extracto original es la fuente de verdad (saldos, ref1/ref2, mandato, nº de factura).
"""
import csv
import xml.etree.ElementTree as ET
from decimal import Decimal
from pathlib import Path


def _cents(s):
    return int(Decimal(s.strip() or "0") * 100)


def _n43(path):
    st, cur = {"lines": []}, None
    for r in Path(path).read_text(encoding="latin1").splitlines():
        if r.startswith("11"):
            st["opening"] = (-1 if r[32] == "1" else 1) * int(r[33:47])
        elif r.startswith("22"):
            cur = {"amount": (-1 if r[27] == "1" else 1) * int(r[28:42]), "ref1": r[52:64].strip(), "ref2": r[64:80].strip(), "detail": []}
            st["lines"].append(cur)
        elif r.startswith("23") and cur:
            cur["detail"] += [r[4:42].strip(), r[42:80].strip()]  # dos campos de concepto de 38
        elif r.startswith("33"):
            st["closing"] = (-1 if r[58] == "1" else 1) * int(r[59:73])
    for l in st["lines"]:
        l["detail"] = " ".join(filter(None, l["detail"]))
    return st


def _camt(path):
    root = ET.parse(path).getroot()
    ns = {"c": root.tag[1:].split("}")[0]}
    sign = lambda e: -1 if e.findtext("c:CdtDbtInd", "", ns) == "DBIT" else 1
    st = {"lines": []}
    for b in root.iterfind(".//c:Bal", ns):
        key = {"OPBD": "opening", "CLBD": "closing"}.get(b.findtext(".//c:Cd", "", ns))
        if key:
            st[key] = sign(b) * _cents(b.findtext("c:Amt", "0", ns))
    for n in root.iterfind(".//c:Ntry", ns):
        st["lines"].append({"bank_line": n.findtext("c:NtryRef", "", ns), "amount": sign(n) * _cents(n.findtext("c:Amt", "0", ns)),
                            "ref1": "", "ref2": n.findtext(".//c:EndToEndId", "", ns).strip(),
                            "detail": " / ".join(filter(None, [n.findtext(".//c:Ustrd", "", ns), n.findtext(".//c:Nm", "", ns)]))})
    return st


def _csv_mx(path):
    rows = [r for r in csv.reader(Path(path).read_text(encoding="utf-8").splitlines()) if r]
    head = dict(zip(rows[0][::2], rows[0][1::2]))
    st = {"opening": _cents(head["Saldo inicial"]), "lines": []}
    st["closing"] = st["opening"]
    for r in rows[2:]:
        f = dict(zip(rows[1], r))
        st["lines"].append({"amount": _cents(f["Abono"]) - _cents(f["Cargo"]), "ref1": f["Clave de rastreo"].strip(),
                            "ref2": f["Referencia"].strip(), "detail": f["Concepto"].strip()})
        st["closing"] = _cents(f["Saldo"])
    return st


def parse(path):
    path = Path(path)
    if path.suffix == ".n43":
        return _n43(path)
    if path.name.endswith(".camt053.xml"):
        return _camt(path)
    if path.suffix == ".csv":
        return _csv_mx(path)
    raise ValueError(f"formato de extracto desconocido: {path}")


def enrich(lines, st):
    """Añade ref1/ref2/detail a las líneas de lines.jsonl. camt casa por id; N43/CSV por orden, verificando el importe."""
    by_id = {l["bank_line"]: l for l in st["lines"] if l.get("bank_line")}
    if not by_id and len(lines) != len(st["lines"]):
        raise ValueError(f"extracto con {len(st['lines'])} líneas y lines.jsonl con {len(lines)}: {lines[:1]}")
    for i, l in enumerate(lines):
        src = by_id.get(l["bank_line"]) if by_id else st["lines"][i]
        if not src or src["amount"] != l["amount"]:
            raise ValueError(f"{l['bank_line']}: el extracto no casa con lines.jsonl ({src and src['amount']} vs {l['amount']})")
        l.update(ref1=src["ref1"], ref2=src["ref2"], detail=src["detail"])
    return lines
