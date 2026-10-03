import json
import sqlite3
from pathlib import Path

import pytest

from common import db

ROOT = Path(__file__).resolve().parents[1]
DEV = ROOT / "participant/phase_dev/inbox/ap"


def test_guarantee_without_de_is_not_missed():
    from tasks.ap_extract import extract_document
    d = extract_document(DEV / 'API004090')
    assert d['retention'] == 1533300
    assert d['payable'] == d['gross'] - d['retention']


def test_xml_credit_keeps_corrective_reference():
    from tasks.ap_extract import extract_document
    d = extract_document(DEV / 'API005583')
    assert d['credit_reference'] == 'F2636258'


def test_deposit_request_has_priority_over_proforma():
    from tasks.ap_extract import extract_document
    d = extract_document(DEV / 'API004469')
    assert d['document_type'] == 'DOWN_PAYMENT_REQUEST'

def test_electricity_cups_is_not_an_iban():
    from tasks.ap_extract import extract_document
    assert extract_document(DEV / 'API004109')['iban'] == 'ES8191037660131301125190'

@pytest.mark.parametrize('doc_id', ['API004095', 'API004091'])
def test_billing_period_is_separate_from_invoice_date(doc_id):
    from tasks.ap_extract import extract_document
    d = extract_document(DEV / doc_id)
    assert d['period_start'] == '2026-06-01'
    assert d['period_end'] == '2026-06-30'


@pytest.mark.parametrize("raw,expected", [
    ("1.234,56", 123456), ("-825,96", -82596),
    ("1,234.56", 123456), ("1234.56", 123456), ("0,00", 0),
])
def test_money_uses_decimal_cents(raw, expected):
    from tasks.ap_extract import money
    assert money(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("30 de junho de 2026", "2026-06-30"),
    ("2026-07-07", "2026-07-07"), ("31/07/2026", "2026-07-31"),
])
def test_dates_are_iso(raw, expected):
    from tasks.ap_extract import date_iso
    assert date_iso(raw) == expected


def test_facturae_reads_totals_parties_items_and_retention():
    from tasks.ap_extract import extract_document
    d = extract_document(DEV / "API004091")
    assert d["invoice_number"] == "2026-035925"
    assert d["invoice_date"] == "2026-07-07"
    assert d["seller_tax_id"] == "A93432007"
    assert d["buyer_tax_id"] == "A12359962"
    assert (d["net"], d["tax"], d["gross"], d["retention"], d["payable"]) == (12449684, 0, 12449684, 622484, 11827200)
    assert sum(l["amount"] for l in d["items"]) == d["net"]
    assert d["items"][0]["po"] == "4500021222"
    assert d["issues"] == []


def test_pdf_reads_parties_payment_and_delivery_lines():
    from tasks.ap_extract import extract_document
    d = extract_document(DEV / "API004203")
    assert d["invoice_number"] == "2026-016702"
    assert d["buyer_tax_id"] == "A12359962"
    assert (d["net"], d["tax"], d["gross"]) == (717214, 150615, 867829)
    assert d["iban"] == "ES9330502964459836343870"
    assert d["items"][0]["receipt_ref"] == "AL-056352"
    assert d["items"][0]["quantity_milli"] == 2030000
    assert d["items"][0]["unit_price"] == 132


def test_portuguese_credit_retains_signed_withholding():
    from tasks.ap_extract import extract_document
    d = extract_document(DEV / "API005588")
    assert d["document_type"] == "CREDIT_NOTE"
    assert (d["net"], d["tax"], d["withholding"], d["payable"]) == (-82596, -18997, -20649, -80944)
    assert d["credit_reference"] == "2026/815"


@pytest.mark.parametrize("doc,kind", [
    ("API005592", "PROFORMA"), ("API005595", "VENDOR_STATEMENT"),
    ("API005189", "FACTORING_NOTICE"), ("API005195", "BANK_DETAILS_CHANGE"),
    ("API005600", "CONTRACTOR_TAX_CERTIFICATE"),
])
def test_notices_are_not_invoices(doc, kind):
    from tasks.ap_extract import extract_document
    assert extract_document(DEV / doc)["document_type"] == kind


def test_missing_extraction_is_explicit_not_zero_or_post(tmp_path):
    from tasks.ap_extract import extract_document
    (tmp_path / "message.json").write_text(json.dumps({"doc_id": "X", "attachments": []}))
    d = extract_document(tmp_path)
    assert d["gross"] is None
    assert d["issues"]
    assert d.get("decision") is None


def test_attachment_cannot_escape_document_directory(tmp_path):
    from tasks.ap_extract import extract_document
    (tmp_path / "message.json").write_text(json.dumps({"doc_id": "X", "attachments": ["../secret.xml"]}))
    with pytest.raises(ValueError, match="attachment"):
        extract_document(tmp_path)


def test_shared_extraction_is_pending_and_never_proposes_journal(tmp_path):
    from tasks.ap_extract import extract_phase
    conn = sqlite3.connect(":memory:")
    conn.executescript(db.SHARED + "CREATE TABLE task_ap_documents(id TEXT)")
    # Publication names its columns: future optional fields cannot shift values.
    conn.execute("ALTER TABLE doc_extract ADD COLUMN review_note TEXT")
    conn.execute("ALTER TABLE ap_result ADD COLUMN review_note TEXT")
    conn.executemany("INSERT INTO task_ap_documents VALUES (?)", [("API004203",), ("API005600",)])
    conn.execute("CREATE TABLE vendors(id TEXT, tax_id TEXT, name TEXT)")
    conn.execute("INSERT INTO vendors VALUES ('V1','A41691415','Ferrer y Cano Hierros y Aceros, S.L.')")
    conn.execute("CREATE TABLE companies(code TEXT,tax_id TEXT,name TEXT)")
    conn.execute("INSERT INTO companies VALUES ('1100','A12359962','Kalmora Construcción, S.A.U.')")
    docs = extract_phase(conn, ROOT / "participant/phase_dev")
    assert len(docs) == 2
    r = conn.execute("SELECT company,vendor_id,payable,decision,data FROM ap_result WHERE doc_id='API004203'").fetchone()
    assert r[:4] == ("1100", "V1", 867829, None)
    assert json.loads(r[4])["status"] == "EXTRACTED_PENDING_DECISION"
    assert conn.execute("SELECT count(*) FROM proposed_je").fetchone()[0] == 0
    conn.execute("UPDATE doc_extract SET review_note='keep' WHERE doc_id='API004203'")
    conn.execute("UPDATE ap_result SET payable=0 WHERE doc_id='API004203'")
    extract_phase(conn, ROOT / "participant/phase_dev")
    assert conn.execute("SELECT review_note FROM doc_extract WHERE doc_id='API004203'").fetchone()[0] == 'keep'
    assert conn.execute("SELECT payable FROM ap_result WHERE doc_id='API004203'").fetchone()[0] == 867829
    conn.execute("UPDATE ap_result SET decision='REJECT' WHERE doc_id='API004203'")
    extract_phase(conn, ROOT / "participant/phase_dev")
    assert conn.execute("SELECT decision FROM ap_result WHERE doc_id='API004203'").fetchone()[0] == 'REJECT'


@pytest.mark.parametrize("doc,currency,tax_id,total", [
    ("API004482", "USD", "95-1294112", 240000),
    ("API004559", "USD", "39-6184738", 1450000),
])
def test_english_currency_tax_ids_and_us_dates(doc, currency, tax_id, total):
    from tasks.ap_extract import extract_document
    d = extract_document(DEV / doc)
    assert (d["currency"], d["seller_tax_id"], d["gross"]) == (currency, tax_id, total)
    assert d["invoice_date"] == "2026-07-01"
    assert not d["issues"]


def test_cfdi_crosschecks_pdf_without_losing_po():
    from tasks.ap_extract import extract_document
    d = extract_document(DEV / "API004315")
    assert d["seller_tax_id"] == "MAT990318UMX"
    assert (d["gross"], d["tax"]) == (107988196, 14894924)
    assert d["po_refs"] == ["4500020412"]
    assert d["items"][0]["receipt_ref"] == "REM-006926"
    assert d["issues"] == []


def test_real_xml_pdf_mismatch_remains_reviewable():
    from tasks.ap_extract import extract_document
    d = extract_document(DEV / "API005228")
    assert "XML_PDF_MISMATCH" in d["issues"]
    assert d["representations"]["pdf"][0]["gross"] == 3169190
    assert d["representations"]["xml"][0]["gross"] == 3254230


def test_scanned_pdf_uses_native_ocr_instead_of_inventing_values():
    from tasks.ap_extract import extract_document
    d = extract_document(DEV / "API005209")
    assert d["invoice_number"] == "IC1000-26-0018"
    assert d["seller_tax_id"] == "A04071952"
    assert d["net"] is not None
    assert "ocr" in d["extraction_methods"]
    assert "NO_READABLE_DOCUMENT" not in d["issues"]


def test_unchanged_source_reuses_cache_without_reparsing(monkeypatch):
    from tasks import ap_extract
    cached = ap_extract.extract_document(DEV / "API004203")
    def should_not_parse(text):
        raise AssertionError("unchanged source reparsed")
    monkeypatch.setattr(ap_extract, "parse_pdf_text", should_not_parse)
    result = ap_extract.extract_document(DEV / "API004203", cached=cached)
    assert result == cached
    result["items"][0]["amount"] = 0
    assert cached["items"][0]["amount"] != 0


def test_changed_metadata_invalidates_cache(tmp_path):
    import shutil
    from tasks.ap_extract import extract_document
    folder = tmp_path / "API004203"
    shutil.copytree(DEV / "API004203", folder)
    cached = extract_document(folder)
    meta = json.loads((folder / "message.json").read_text())
    meta["received_at"] = "2026-07-31T23:00:00"
    (folder / "message.json").write_text(json.dumps(meta))
    fresh = extract_document(folder, cached=cached)
    assert fresh["source_hash"] != cached["source_hash"]
    assert fresh["metadata"]["received_at"] == meta["received_at"]


def test_ocr_failure_is_explicit_and_does_not_abort_other_documents(monkeypatch):
    import subprocess
    from tasks import ap_extract
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("ap-ocr", 30)
    monkeypatch.setattr(ap_extract.subprocess, "run", timeout)
    d = ap_extract.extract_document(DEV / "API005209")
    assert any(i.startswith("PARSE_ERROR:") for i in d["issues"])
    assert "NO_READABLE_DOCUMENT" in d["issues"]


@pytest.mark.parametrize("doc,number", [("API005199", "2026-030797"), ("API005205", "2026-032015")])
def test_ocr_preserves_complete_delivery_tables(doc, number):
    from tasks.ap_extract import extract_document
    d = extract_document(DEV / doc)
    assert d["invoice_number"] == number
    assert sum(i["amount"] for i in d["items"]) == d["net"]
    assert all(i["quantity_milli"] is not None for i in d["items"])
    assert not d["issues"]


def test_ocr_decimal_point_misread_as_group_separator():
    from tasks.ap_extract import money
    assert money("1.325.28") == 132528


def test_cfdi_credit_normalizes_e_document_sign_not_false_mismatch():
    from tasks.ap_extract import extract_document
    d = extract_document(DEV / "API005591")
    assert d["document_type"] == "CREDIT_NOTE"
    assert (d["net"], d["tax"], d["gross"]) == (-41022632, -6563621, -47586253)
    assert sum(i["amount"] for i in d["items"]) == d["net"]
    assert "XML_PDF_MISMATCH" not in d["issues"]


@pytest.mark.parametrize("phase,count", [("dev", 305), ("test", 297)])
def test_complete_phase_produces_pending_identity_for_every_source(phase, count, tmp_path, monkeypatch):
    from tasks.ap_extract import extract_phase
    monkeypatch.setattr(db, "CACHE", tmp_path / "cache")
    conn = db.build_db(db.PHASES[phase], tmp_path / "phase.db")
    try:
        docs = extract_phase(conn, db.PHASES[phase])
        assert len(docs) == count
        assert len({d["doc_id"] for d in docs}) == count
        assert conn.execute("SELECT count(*) FROM ap_result").fetchone()[0] == count
        assert conn.execute("SELECT count(*) FROM ap_result WHERE decision IS NOT NULL").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM proposed_je").fetchone()[0] == 0
        assert all(d["document_type"] and d["source_hash"] for d in docs)
        assert not any("NO_READABLE_DOCUMENT" in d["issues"] for d in docs)
    finally:
        conn.close()


@pytest.mark.parametrize("seller,buyer,expected", [
    (" esa41691415 ", " esa12359962 ", ("V1", "1100")),
    (None, None, (None, None)),
    ("UNKNOWN", "UNKNOWN", (None, None)),
])
def test_identity_resolution_normalizes_once_without_guessing(seller, buyer, expected, monkeypatch):
    from tasks import ap_extract
    document = ap_extract.extract_document(DEV / "API004203")
    document.update(seller_tax_id=seller, buyer_tax_id=buyer)
    monkeypatch.setattr(ap_extract, "extract_document", lambda *a, **kw: document)
    conn = sqlite3.connect(":memory:")
    conn.executescript(db.SHARED + """
        CREATE TABLE task_ap_documents(id TEXT);
        INSERT INTO task_ap_documents VALUES ('API004203');
        CREATE TABLE vendors(id TEXT, tax_id TEXT, name TEXT);
        INSERT INTO vendors VALUES ('EMPTY', NULL, 'Unknown');
        INSERT INTO vendors VALUES ('V1', 'A41691415', 'Ferrer y Cano Hierros y Aceros, S.L.');
        INSERT INTO vendors VALUES ('V2', 'ESA41691415', 'Second master row');
        CREATE TABLE companies(code TEXT, tax_id TEXT, name TEXT);
        INSERT INTO companies VALUES ('EMPTY', NULL, 'Unknown');
        INSERT INTO companies VALUES ('1100', 'A12359962', 'Kalmora Construcción, S.A.U.');
        INSERT INTO companies VALUES ('OTHER', 'ESA12359962', 'Second master row');
    """)
    try:
        result = ap_extract.extract_phase(conn, DEV.parents[1])[0]
        assert (result["vendor_id"], result["company"]) == expected
        assert conn.row_factory is None
    finally:
        conn.close()
