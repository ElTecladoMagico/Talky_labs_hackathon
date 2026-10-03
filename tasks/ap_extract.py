"""P1 extraction only: source documents -> reusable cache + pending identities.

Run with: python -m tasks.ap_extract dev|test [--rebuild]. No golden inputs,
no provisional POST decisions, no journal entries. Accounting is a separate gate.
"""
import hashlib
import json
import re
import sys
import subprocess
import unicodedata
import xml.etree.ElementTree as ET
from copy import deepcopy
from datetime import date
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from pathlib import Path

from common import db
from common.je import norm_num

VERSION = 5
AMOUNT = r"-?\d[\d.,]*[.,]\d{2}"
INVOICE_KINDS = {"INVOICE", "CREDIT_NOTE", "DOWN_PAYMENT_REQUEST"}


def fold(value):
    return "".join(c for c in unicodedata.normalize("NFKD", value.lower()) if not unicodedata.combining(c))


def money(raw):
    s = re.sub(r"[^\d.,+-]", "", raw)
    separator = "," if s.rfind(",") > s.rfind(".") else "."
    if separator in s:
        whole, fraction = s.rsplit(separator, 1)
        s = whole.replace(".", "").replace(",", "") + "." + fraction
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
    value = _match(pattern + rf"\s*:?\s*(?:(?:EUR|USD|GBP|MXN|[$£])\s*)?({AMOUNT})", text)
    return money(value) if value is not None else None


def _kind(text):
    t = fold(text)
    for marker, kind in [
        ("deposit request", "DOWN_PAYMENT_REQUEST"),
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
    # ponytail: template tables only; unmatched layouts stay explicit review issues.
    tokens = []
    for raw in body.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        combined = re.fullmatch(r"(-?[\d.,]+)\s+([\w²/%]+)", raw)
        tokens.extend(combined.groups() if combined else [raw])
    items, description, i = [], [], 0
    headers = {"cant.", "ud.", "precio", "importe", "qtd.", "un.", "preço", "valor", "código", "qty", "unit", "unit price", "amount", "cant. ud.", "qtd. un."}
    while i < len(tokens):
        token = tokens[i]
        if token.lower() in headers:
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
    d["invoice_number"] = _match(r'(?:N[º°o] Factura|Fatura N[.º°"]+|Invoice No\.?|Invoice number)\s*:\s*([^\n]+)', text)
    raw_date = _match(r"^(?:Fecha|Data|Date|Invoice Date)\s*:\s*([^\n]+)", text)
    if raw_date and re.search(r"^TOTAL\s*\n\$", text, re.M) and "/" in raw_date:
        month, day, year = map(int, raw_date.split("/"))
        raw_date = date(year, month, day).isoformat()
    d["invoice_date"] = date_iso(raw_date) if raw_date else None
    nifs = re.findall(r"\b(?:NIF|RFC|Tax ID)\s*:?\s*([A-Z0-9-]+)", text)
    d["seller_tax_id"] = nifs[0] if nifs else None
    recipient = re.split(r"FACTURAR A|FATURAR A|BILL TO", text, maxsplit=1)
    d["buyer_tax_id"] = _match(r"\b(?:NIF|RFC|Tax ID)\s*:\s*([A-Z0-9-]+)", recipient[1]) if len(recipient) == 2 else None
    d["net"] = _amount(r"^(?:Base imponible|Incidência|Subtotal)", text)
    d["tax"] = _amount(r"^IVA[^\n]*\n", text)
    d["gross"] = _amount(r"^TOTAL(?: FACTURA)?", text)
    d["currency"] = _match(rf"{AMOUNT}\s+(EUR|USD|GBP|MXN)\b", text) or _match(rf"\b(EUR|USD|GBP|MXN)\s+{AMOUNT}", text)
    if d["currency"] is None:
        d["currency"] = "USD" if re.search(r"^TOTAL\s*\n\$", text, re.M) else ("GBP" if "£" in text else None)
    d["withholding"] = _amount(r"^(?:Retención (?:IRPF|ISR|IVA)[^\n]*|Retenção IRS[^\n]*)\n", text) or 0
    d["retention"] = _amount(r"^(?:Retención (?:de )?garantía[^\n]*|Retención 5[^\n]*|Retenção 5[^\n]*)\n", text) or 0
    if d["net"] is not None:
        sign = -1 if d["net"] < 0 else 1
        d["withholding"] = sign * abs(d["withholding"])
        d["retention"] = sign * abs(d["retention"])
    d["payable"] = _amount(r"^(?:Total a pagar|TOTAL A PAGAR|Importe a pagar|Amount due)", text)
    if d["payable"] is None and d["gross"] is not None:
        d["payable"] = d["gross"] - d["withholding"] - d["retention"]
    d["iban"] = _match(r"\b((?:ES|PT|DE|FR|GB|NL|IT|IE)\d{2}[A-Z0-9]{10,30})\b", text)
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
        result = {"document_type": "CREDIT_NOTE" if root.get("TipoDeComprobante") == "E" else "INVOICE", "invoice_number": root.get("Folio"), "invoice_date": date_iso(root.get("Fecha")), "currency": root.get("Moneda"), "seller_tax_id": seller.get("Rfc"), "buyer_tax_id": buyer.get("Rfc"), "net": money(root.get("SubTotal")), "tax": tax, "gross": gross, "withholding": withholding, "retention": 0, "payable": money(root.get("Total")), "items": items}
        if result["document_type"] == "CREDIT_NOTE":
            for field in ("net", "tax", "gross", "withholding", "payable"):
                result[field] = -abs(result[field])
            for item in items:
                item["amount"] = -abs(item["amount"])
        return result
    if root.tag != "Facturae":
        raise ValueError("unsupported XML schema")
    items = [_receipt({"description": e.findtext("ItemDescription", ""), "quantity_milli": int(Decimal(e.findtext("Quantity")) * 1000), "unit_price": money(e.findtext("UnitPriceWithoutTax")), "amount": money(e.findtext("GrossAmount")), "po": e.findtext("IssuerTransactionReference")}) for e in root.findall(".//InvoiceLine")]
    return {"document_type": "CREDIT_NOTE" if txt("InvoiceClass") in {"OR", "CR"} else "INVOICE", "credit_reference": txt("Corrective/InvoiceNumber"), "invoice_number": txt("InvoiceNumber"), "invoice_date": date_iso(txt("IssueDate")), "currency": txt("InvoiceCurrencyCode"), "seller_tax_id": txt("SellerParty/TaxIdentification/TaxIdentificationNumber"), "buyer_tax_id": txt("BuyerParty/TaxIdentification/TaxIdentificationNumber"), "net": cents("InvoiceTotals/TotalGrossAmountBeforeTaxes"), "tax": cents("InvoiceTotals/TotalTaxOutputs"), "gross": cents("InvoiceTotals/InvoiceTotal"), "withholding": cents("InvoiceTotals/TotalTaxesWithheld") or 0, "retention": cents("InvoiceTotals/AmountsWithheld/WithholdingAmount") or 0, "payable": cents("InvoiceTotals/TotalOutstandingAmount"), "items": items, "po_refs": list(dict.fromkeys(e["po"] for e in items if e["po"])), "text": txt("InvoiceAdditionalInformation") or ""}


def extract_document(folder, cached=None):
    folder = Path(folder)
    metadata = json.loads((folder / "message.json").read_text(encoding="utf-8"))
    paths = [(folder / name).resolve() for name in metadata["attachments"]]
    if any(not p.is_relative_to(folder.resolve()) for p in paths):
        raise ValueError("unsafe attachment path")
    d = dict.fromkeys(("invoice_number", "invoice_date", "currency", "seller_tax_id", "buyer_tax_id", "net", "tax", "gross", "payable", "iban", "credit_reference"))
    d.update(doc_id=metadata.get("doc_id", folder.name), document_type=None, items=[], po_refs=[], withholding=0, retention=0, text="", issues=[], metadata=metadata, schema_version=VERSION, extraction_methods=[])
    digest = hashlib.sha256((folder / "message.json").read_bytes())
    for p in paths:
        if p.is_file():
            digest.update(p.name.encode() + p.read_bytes())
        else:
            digest.update(b"MISSING:" + p.name.encode())
    if cached and cached.get("schema_version") == VERSION and cached.get("source_hash") == digest.hexdigest():
        return deepcopy(cached)
    pdfs, xmls = [], []
    for p in paths:
        if not p.is_file():
            d["issues"].append(f"MISSING_ATTACHMENT:{p.name}")
            continue
        try:
            if p.suffix.lower() == ".xml":
                xmls.append(parse_xml(p))
                d["extraction_methods"].append("xml")
            elif p.suffix.lower() == ".pdf":
                from pypdf import PdfReader
                text = "\n".join(page.extract_text() or "" for page in PdfReader(p).pages)
                ocr = Path(sys.executable).parent / "ap-ocr"
                if not text.strip() and sys.platform == "darwin" and ocr.is_file():
                    result = subprocess.run([str(ocr), str(p)], capture_output=True, text=True, timeout=30)
                    if result.returncode == 0:
                        text = result.stdout
                        d["extraction_methods"].append("ocr")
                    else:
                        d["issues"].append(f"OCR_FAILED:{p.name}:{result.stderr[:200]}")
                if text.strip():
                    pdfs.append(parse_pdf_text(text))
                    if "ocr" not in d["extraction_methods"]:
                        d["extraction_methods"].append("pdf")
                else:
                    d["issues"].append(f"OCR_REQUIRED:{p.name}")
            else:
                d["issues"].append(f"UNSUPPORTED_ATTACHMENT:{p.name}")
        except (ValueError, InvalidOperation, ET.ParseError, OSError, subprocess.TimeoutExpired) as exc:
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
    fields = ("invoice_number", "invoice_date", "net", "tax", "gross", "withholding", "retention", "payable", "currency", "seller_tax_id", "buyer_tax_id")
    d["representations"] = {kind: [{k: representation.get(k) for k in fields} for representation in sources]
                            for kind, sources in (("pdf", pdfs), ("xml", xmls))}
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
    return re.sub(r"^(?:ES|PT)", "", (value or "").strip().upper())


def _rows(conn, table):
    cursor = conn.execute(f"SELECT * FROM {table}")
    names = [col[0] for col in cursor.description]
    return [dict(zip(names, row)) for row in cursor]


def extract_phase(conn, phase_dir):
    vendors, companies = _rows(conn, "vendors"), _rows(conn, "companies")
    # Keep the previous first-match rule when master rows share a tax identifier.
    vendors_by_tax = {_tax_id(v["tax_id"]): v for v in reversed(vendors) if _tax_id(v["tax_id"])}
    companies_by_tax = {_tax_id(c["tax_id"]): c for c in reversed(companies) if _tax_id(c["tax_id"])}
    docs = []
    for (doc_id,) in conn.execute("SELECT id FROM task_ap_documents ORDER BY id").fetchall():
        saved = conn.execute("SELECT data FROM doc_extract WHERE doc_id=?", (doc_id,)).fetchone()
        d = extract_document(Path(phase_dir) / "inbox/ap" / doc_id, cached=json.loads(saved[0]) if saved else None)
        vendor = vendors_by_tax.get(_tax_id(d["seller_tax_id"]))
        if vendor is None and d["document_type"] not in INVOICE_KINDS:
            text = fold(d["text"])
            vendor = next((v for v in vendors if fold(v["name"]) in text), None)
        company = companies_by_tax.get(_tax_id(d["buyer_tax_id"]))
        d.update(vendor_id=vendor["id"] if vendor else None, company=company["code"] if company else None, status="EXTRACTED_PENDING_DECISION")
        params = dict(d, doc_id=doc_id, data=json.dumps(d, ensure_ascii=False), decision=None,
                      invoice_norm=norm_num(d["invoice_number"]) if d["invoice_number"] else None,
                      source="xml" if any(p.endswith(".xml") for p in d["source_files"]) else "pdf",
                      confidence=0.5 if d["issues"] else 1.0)
        conn.execute("""INSERT INTO doc_extract(doc_id, source, confidence, data)
                        VALUES (:doc_id, :source, :confidence, :data) ON CONFLICT(doc_id) DO UPDATE SET
                        source=excluded.source, confidence=excluded.confidence, data=excluded.data""", params)
        # Refresh pending identities; preserve final decisions on extraction-only reruns.
        conn.execute("""INSERT INTO ap_result(doc_id, company, vendor_id, invoice_number, invoice_norm,
                                             invoice_date, payable, currency, decision, data)
                        VALUES (:doc_id, :company, :vendor_id, :invoice_number, :invoice_norm,
                                :invoice_date, :payable, :currency, :decision, :data)
                        ON CONFLICT(doc_id) DO UPDATE SET
                        company=excluded.company, vendor_id=excluded.vendor_id, invoice_number=excluded.invoice_number,
                        invoice_norm=excluded.invoice_norm, invoice_date=excluded.invoice_date, payable=excluded.payable,
                        currency=excluded.currency, data=excluded.data WHERE ap_result.decision IS NULL""",
                     params)
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
