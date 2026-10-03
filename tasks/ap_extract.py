"""P1 extraction only: source documents -> reusable cache + pending identities.

Run with: python -m tasks.ap_extract dev|test [--rebuild]. No golden inputs,
no provisional POST decisions, no journal entries. Accounting is a separate gate.
"""
import hashlib
import json
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from common import db
from common.je import norm_num

VERSION = 1
AMOUNT = r"-?\d[\d.,]*[.,]\d{2}"
INVOICE_KINDS = {"INVOICE", "CREDIT_NOTE", "DOWN_PAYMENT_REQUEST"}


def fold(value):
    return "".join(c for c in unicodedata.normalize("NFKD", value.lower()) if not unicodedata.combining(c))


def money(raw):
    s = re.sub(r"[^\d.,+-]", "", raw)
    separator = "," if s.rfind(",") > s.rfind(".") else "."
    if separator in s:
        other = "." if separator == "," else ","
        s = s.replace(other, "").replace(separator, ".")
    return int((Decimal(s) * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def date_iso(raw):
    raw = fold(raw.strip())
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", raw)
    if m:
        return date(*map(int, m.groups())).isoformat()
    m = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", raw)
    if m:
        day, month, year = map(int, m.groups())
        return date(year, month, day).isoformat()
    months = "janeiro fevereiro marco abril maio junho julho agosto setembro outubro novembro dezembro".split()
    spanish = "enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre".split()
    m = re.search(r"(\d{1,2}) de (\w+) de (\d{4})", raw)
    if m:
        day, month, year = m.groups()
        names = months if month in months else spanish
        return date(int(year), names.index(month) + 1, int(day)).isoformat()
    raise ValueError(f"unrecognized date: {raw}")


def _match(pattern, text):
    m = re.search(pattern, text, re.I | re.M)
    return m.group(1).strip() if m else None


def _amount(pattern, text):
    value = _match(pattern + rf"\s*:?\s*({AMOUNT})", text)
    return money(value) if value is not None else None


def _kind(text):
    t = fold(text)
    for marker, kind in [
        ("proforma", "PROFORMA"), ("extracto de cuenta", "VENDOR_STATEMENT"),
        ("recordatorio de pago", "VENDOR_STATEMENT"), ("cesion de creditos", "FACTORING_NOTICE"),
        ("diligencia de embargo", "TAX_GARNISHMENT_ORDER"),
        ("cambio de cuenta bancaria", "BANK_DETAILS_CHANGE"),
        ("certificado de estar al corriente", "CONTRACTOR_TAX_CERTIFICATE"),
        ("nota de credito", "CREDIT_NOTE"), ("rectificativa", "CREDIT_NOTE"),
        ("solicitud de anticipo", "DOWN_PAYMENT_REQUEST"),
        ("down payment request", "DOWN_PAYMENT_REQUEST"),
    ]:
        if marker in t:
            return kind
    return "INVOICE"


def _receipt(item):
    item["receipt_ref"] = _match(r"\b((?:AL|GR|REM)-\d+)\b", item["description"])
    return item


def _pdf_items(text):
    start = re.search(r"^(?:Descripción|Descrição|Description)\s*$", text, re.M)
    if not start:
        return []
    body = re.split(r"^(?:Base imponible|Incidência|Certificado a origen|Subtotal)\b", text[start.end():], maxsplit=1, flags=re.M)[0]
    tokens = [s.strip() for s in body.splitlines() if s.strip()]
    items, description, i = [], [], 0
    headers = {"Cant.", "Ud.", "Precio", "Importe", "Qtd.", "Un.", "Preço", "Valor", "Código"}
    while i < len(tokens):
        token = tokens[i]
        if token in headers:
            i += 1
            continue
        if description and i + 3 < len(tokens) and re.fullmatch(r"-?[\d.,]+", token) and re.fullmatch(r"[\w²/%]+", tokens[i+1]) and re.fullmatch(AMOUNT, tokens[i+2]) and re.fullmatch(AMOUNT, tokens[i+3]):
            qty = Decimal(token.replace(".", "").replace(",", "."))
            items.append(_receipt({"description": " ".join(description), "quantity_milli": int(qty * 1000), "unit_price": money(tokens[i+2]), "amount": money(tokens[i+3]), "po": None}))
            description, i = [], i + 4
            continue
        if description and re.fullmatch(AMOUNT, token):
            items.append(_receipt({"description": " ".join(description), "quantity_milli": None, "unit_price": None, "amount": money(token), "po": None}))
            description = []
        else:
            description.append(token)
        i += 1
    return items


def parse_pdf_text(text):
    d = {"document_type": _kind(text), "text": text}
    d["invoice_number"] = _match(r"(?:Nº Factura|Fatura N.º|Invoice No\.?|Invoice number)\s*:\s*([^\n]+)", text)
    raw_date = _match(r"^(?:Fecha|Data|Date)\s*:\s*([^\n]+)", text)
    d["invoice_date"] = date_iso(raw_date) if raw_date else None
    nifs = re.findall(r"\b(?:NIF|RFC)\s*:?\s*([A-Z0-9]+)", text)
    d["seller_tax_id"] = nifs[0] if nifs else None
    recipient = re.split(r"FACTURAR A|FATURAR A|BILL TO", text, maxsplit=1)
    d["buyer_tax_id"] = _match(r"\b(?:NIF|RFC)\s*:\s*([A-Z0-9]+)", recipient[1]) if len(recipient) == 2 else None
    d["net"] = _amount(r"^(?:Base imponible|Incidência|Subtotal)", text)
    d["tax"] = _amount(r"^IVA[^\n]*\n", text)
    d["gross"] = _amount(r"^TOTAL(?: FACTURA)?", text)
    d["currency"] = _match(rf"{AMOUNT}\s+(EUR|USD|GBP|MXN)\b", text)
    d["withholding"] = _amount(r"^(?:Retención (?:IRPF|ISR|IVA)[^\n]*|Retenção IRS[^\n]*)\n", text) or 0
    d["retention"] = _amount(r"^(?:Retención (?:de garantía|5[^\n]*)|Retenção 5[^\n]*)\n", text) or 0
    if d["net"] is not None:
        sign = -1 if d["net"] < 0 else 1
        d["withholding"] = sign * abs(d["withholding"])
        d["retention"] = sign * abs(d["retention"])
    d["payable"] = _amount(r"^(?:Total a pagar|TOTAL A PAGAR|Importe a pagar|Amount due)", text)
    if d["payable"] is None and d["gross"] is not None:
        d["payable"] = d["gross"] - d["withholding"] - d["retention"]
    d["iban"] = _match(r"\b((?:ES|PT|DE|FR|GB|NL|IT)\d{2}[A-Z0-9]{10,30})\b", text)
    d["po_refs"] = list(dict.fromkeys(re.findall(r"\b450\d{7}\b", text)))
    d["items"] = _pdf_items(text)
    if len(d["po_refs"]) == 1:
        for item in d["items"]:
            item["po"] = d["po_refs"][0]
    d["credit_reference"] = _match(r"Rectifica la factura nº\s+([^\s.]+)", text)
    d["current_certification"] = _amount(r"^Importe de esta certificación", text)
    d["cumulative_certification"] = _amount(r"^Certificado a origen", text)
    return d


def parse_xml(path):
    root = ET.parse(path).getroot()
    for element in root.iter():
        element.tag = element.tag.split("}")[-1]
    def txt(name):
        return root.findtext(".//" + name)
    def cents(name):
        value = txt(name)
        return money(value) if value is not None else None
    if root.tag == "Comprobante":
        seller, buyer, taxes = root.find("Emisor"), root.find("Receptor"), root.find("Impuestos")
        items = [_receipt({"description": e.get("Descripcion", ""), "quantity_milli": int(Decimal(e.get("Cantidad")) * 1000), "unit_price": money(e.get("ValorUnitario")), "amount": money(e.get("Importe")), "po": None}) for e in root.findall(".//Concepto")]
        tax = money(taxes.get("TotalImpuestosTrasladados", "0")) if taxes is not None else 0
        withholding = money(taxes.get("TotalImpuestosRetenidos", "0")) if taxes is not None else 0
        gross = money(root.get("Total")) + withholding
        return {"document_type": "CREDIT_NOTE" if root.get("TipoDeComprobante") == "E" else "INVOICE", "invoice_number": root.get("Folio"), "invoice_date": date_iso(root.get("Fecha")), "currency": root.get("Moneda"), "seller_tax_id": seller.get("Rfc"), "buyer_tax_id": buyer.get("Rfc"), "net": money(root.get("SubTotal")), "tax": tax, "gross": gross, "withholding": withholding, "retention": 0, "payable": money(root.get("Total")), "items": items}
    if root.tag != "Facturae":
        raise ValueError("unsupported XML schema")
    items = [_receipt({"description": e.findtext("ItemDescription", ""), "quantity_milli": int(Decimal(e.findtext("Quantity")) * 1000), "unit_price": money(e.findtext("UnitPriceWithoutTax")), "amount": money(e.findtext("GrossAmount")), "po": e.findtext("IssuerTransactionReference")}) for e in root.findall(".//InvoiceLine")]
    return {"document_type": "CREDIT_NOTE" if txt("InvoiceClass") in {"OR", "CR"} else "INVOICE", "invoice_number": txt("InvoiceNumber"), "invoice_date": date_iso(txt("IssueDate")), "currency": txt("InvoiceCurrencyCode"), "seller_tax_id": txt("SellerParty/TaxIdentification/TaxIdentificationNumber"), "buyer_tax_id": txt("BuyerParty/TaxIdentification/TaxIdentificationNumber"), "net": cents("InvoiceTotals/TotalGrossAmountBeforeTaxes"), "tax": cents("InvoiceTotals/TotalTaxOutputs"), "gross": cents("InvoiceTotals/InvoiceTotal"), "withholding": cents("InvoiceTotals/TotalTaxesWithheld") or 0, "retention": cents("InvoiceTotals/AmountsWithheld/WithholdingAmount") or 0, "payable": cents("InvoiceTotals/TotalOutstandingAmount"), "items": items, "po_refs": list(dict.fromkeys(e["po"] for e in items if e["po"])), "text": txt("InvoiceAdditionalInformation") or ""}


def extract_document(folder):
    folder = Path(folder)
    metadata = json.loads((folder / "message.json").read_text(encoding="utf-8"))
    paths = [(folder / name).resolve() for name in metadata["attachments"]]
    if any(not p.is_relative_to(folder.resolve()) for p in paths):
        raise ValueError("unsafe attachment path")
    d = dict.fromkeys(("invoice_number", "invoice_date", "currency", "seller_tax_id", "buyer_tax_id", "net", "tax", "gross", "payable", "iban", "credit_reference"))
    d.update(doc_id=metadata.get("doc_id", folder.name), document_type=None, items=[], po_refs=[], withholding=0, retention=0, text="", issues=[], metadata=metadata, schema_version=VERSION)
    digest = hashlib.sha256((folder / "message.json").read_bytes())
    pdfs, xmls = [], []
    for p in paths:
        if not p.is_file():
            d["issues"].append(f"MISSING_ATTACHMENT:{p.name}")
            continue
        digest.update(p.name.encode() + p.read_bytes())
        try:
            if p.suffix.lower() == ".xml":
                xmls.append(parse_xml(p))
            elif p.suffix.lower() == ".pdf":
                from pypdf import PdfReader
                text = "\n".join(page.extract_text() or "" for page in PdfReader(p).pages)
                if text.strip():
                    pdfs.append(parse_pdf_text(text))
                else:
                    d["issues"].append(f"OCR_REQUIRED:{p.name}")
            else:
                d["issues"].append(f"UNSUPPORTED_ATTACHMENT:{p.name}")
        except (ValueError, ET.ParseError, OSError) as exc:
            d["issues"].append(f"PARSE_ERROR:{p.name}:{exc}")
    if pdfs:
        d.update(pdfs[0])
    if xmls:
        if pdfs and any(xmls[0].get(k) != pdfs[0].get(k) for k in ("invoice_number", "net", "gross", "seller_tax_id", "buyer_tax_id")):
            d["issues"].append("XML_PDF_MISMATCH")
        # PDF holds evidence absent from XML: bank details, PO references, legends.
        d.update(xmls[0], text="\n".join([d["text"], xmls[0].get("text", "")]))
        if pdfs and not d["po_refs"]:
            d["po_refs"] = pdfs[0]["po_refs"]
        if len(d["po_refs"]) == 1:
            for item in d["items"]:
                item["po"] = item.get("po") or d["po_refs"][0]
    if not pdfs and not xmls:
        d["issues"].append("NO_READABLE_DOCUMENT")
    if d["document_type"] in INVOICE_KINDS:
        for field in ("invoice_number", "invoice_date", "currency", "seller_tax_id", "net", "tax", "gross", "payable"):
            if d[field] is None:
                d["issues"].append(f"MISSING_EXTRACTION:{field}")
        if d["net"] is not None and sum(i["amount"] for i in d["items"]) != d["net"]:
            d["issues"].append("ITEM_SUM_MISMATCH")
    d["source_files"] = metadata["attachments"]
    d["source_hash"] = digest.hexdigest()
    return d


def _tax_id(value):
    return re.sub(r"^(?:ES|PT)", "", value or "").upper()


def _rows(conn, table):
    cursor = conn.execute(f"SELECT * FROM {table}")
    names = [col[0] for col in cursor.description]
    return [dict(zip(names, row)) for row in cursor]


def extract_phase(conn, phase_dir):
    vendors, companies = _rows(conn, "vendors"), _rows(conn, "companies")
    docs = []
    for (doc_id,) in conn.execute("SELECT id FROM task_ap_documents ORDER BY id").fetchall():
        d = extract_document(Path(phase_dir) / "inbox/ap" / doc_id)
        vendor = next((v for v in vendors if _tax_id(v["tax_id"]) == _tax_id(d["seller_tax_id"]) and d["seller_tax_id"]), None)
        if vendor is None and d["document_type"] not in INVOICE_KINDS:
            vendor = next((v for v in vendors if fold(v["name"]) in fold(d["text"])), None)
        company = next((c for c in companies if _tax_id(c["tax_id"]) == _tax_id(d["buyer_tax_id"]) and d["buyer_tax_id"]), None)
        d.update(vendor_id=vendor["id"] if vendor else None, company=company["code"] if company else None, status="EXTRACTED_PENDING_DECISION")
        payload = json.dumps(d, ensure_ascii=False)
        conn.execute("INSERT OR REPLACE INTO doc_extract VALUES (?,?,?,?)", (doc_id, "xml" if any(p.endswith(".xml") for p in d["source_files"]) else "pdf", 0.5 if d["issues"] else 1.0, payload))
        # DO NOTHING preserves a colleague's/final decision on extraction-only reruns.
        conn.execute("INSERT INTO ap_result VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(doc_id) DO NOTHING", (doc_id, d["company"], d["vendor_id"], d["invoice_number"], norm_num(d["invoice_number"]) if d["invoice_number"] else None, d["invoice_date"], d["payable"], d["currency"], None, payload))
        docs.append(d)
    return docs


def main(phase, rebuild=False):
    conn = db.connect(phase, rebuild=rebuild)
    try:
        docs = extract_phase(conn, db.PHASES[phase])
        conn.commit()
        db.dump_cache(conn, db.PHASES[phase])
        problems = [d for d in docs if d["issues"]]
        print(f"{len(docs)} extracted; {len(problems)} require review; no decisions or journals published")
        for d in problems:
            print(d["doc_id"], ", ".join(d["issues"]))
    finally:
        conn.close()


if __name__ == "__main__":
    main(sys.argv[1], "--rebuild" in sys.argv)
