"""P1/P3 contract: source-backed fee journal and duplicate suppression."""
import json
import sqlite3
import pytest
from common import db

@pytest.fixture(scope='session')
def base_db(tmp_path_factory):
    c = db.build_db(db.PHASES['dev'], tmp_path_factory.mktemp('ap') / 'base.db')
    yield c
    c.close()

@pytest.fixture
def full_conn(base_db):
    c = sqlite3.connect(':memory:')
    base_db.backup(c)
    yield c
    c.close()

@pytest.fixture
def conn(full_conn):
    c = full_conn
    c.execute("DELETE FROM task_ap_documents WHERE id NOT IN ('API004299', 'API005210')")
    return c

def test_fee_posts_supplier_assignment_and_shared_decisions(conn):
    from tasks.ap import run
    rows = {r['doc_id']: r for r in run(conn)}
    assert rows['API004299']['decision'] == 'POST'
    assert rows['API005210']['decision'] == 'DUPLICATE'
    assert rows['API005210']['duplicate_of'] == 'API004299'
    assert rows['API005210']['journal_entry'] is None
    assert conn.execute("SELECT doc_id, vendor_id, invoice_number, decision FROM ap_result ORDER BY doc_id").fetchall() == [
        ('API004299', 'V100173', '26012023', 'POST'),
        ('API005210', 'V100173', '26012023', 'DUPLICATE')]
    assert rows['API005210']['source_invoice_number'] == 'F-26012023'
    assert conn.execute("SELECT account, debit, credit, partner, assignment FROM ledger WHERE origin='P1' ORDER BY account").fetchall() == [
        ('41000000', 0, 828850, 'V100173', '26012023'),
        ('47200000', 143850, 0, None, None),
        ('62300000', 685000, 0, None, None)]
    assert conn.execute("SELECT cost_center FROM ledger WHERE origin='P1' AND account='62300000'").fetchone() == ('CC-1300-ADM',)
    assert conn.execute("SELECT event_key FROM proposed_je WHERE owner='P1'").fetchall() == [('ap:API004299',)]

def test_rerun_is_idempotent_and_preserves_other_owners(conn):
    from tasks.ap import run
    conn.execute("INSERT INTO bank_explained VALUES ('sentinel','bank','cash','UNRECORDED_RECEIPT','P2','receipt')")
    conn.execute("INSERT INTO proposed_je VALUES ('other','P3','ar_cash','1300','[]')")
    first = run(conn)
    assert run(conn) == first
    assert conn.execute("SELECT COUNT(*) FROM proposed_je").fetchone()[0] == 2
    assert conn.execute("SELECT category FROM bank_explained WHERE bank_line='sentinel'").fetchone()[0] == 'UNRECORDED_RECEIPT'

def test_conflicting_event_is_not_silently_reused(conn):
    from tasks.ap import run
    conn.execute("INSERT INTO proposed_je VALUES ('ap:API004299','P3','ar_cash','1300','[]')")
    with pytest.raises(ValueError, match='conflict'):
        run(conn)

@pytest.mark.parametrize('change,expected', [
    ({'issues': ['XML_PDF_MISMATCH']}, 'HOLD'), ({'iban': 'OTHER'}, 'HOLD'),
    ({'gross': 1}, 'REJECT'), ({'withholding': 1}, 'REJECT'),
    ({'po_refs': ['PO']}, 'HOLD'),
])
def test_unsafe_original_is_decided_without_posting(conn, monkeypatch, change, expected):
    from tasks import ap
    from tasks.ap_extract import extract_phase
    # Isolate the unsafe original: changing currency/amount makes a different
    # duplicate key, so a separate valid submission need not be rejected.
    docs = extract_phase(conn, db.PHASES['dev'])[:1]
    docs[0].update(change)
    monkeypatch.setattr(ap, 'extract_phase', lambda *_: docs)
    ap.run(conn)
    assert conn.execute("SELECT decision FROM ap_result WHERE doc_id='API004299'").fetchone()[0] == expected
    assert conn.execute("SELECT COUNT(*) FROM proposed_je").fetchone()[0] == 0

def test_missing_cost_evidence_does_not_guess(conn):
    from tasks.ap import run
    conn.execute("DELETE FROM je_line WHERE account='62300000'")
    run(conn)
    assert conn.execute("SELECT decision FROM ap_result WHERE doc_id='API004299'").fetchone()[0] == 'HOLD'
    assert conn.execute("SELECT COUNT(*) FROM proposed_je").fetchone()[0] == 0

def test_pipeline_publishes_before_downstream_netting(conn, tmp_path, monkeypatch):
    import run as pipeline
    from tasks.ap import run
    observed = []
    def downstream(c):
        observed.extend(c.execute("SELECT partner, assignment, credit FROM ledger WHERE origin='P1' AND account='41000000'").fetchall())
        return []
    monkeypatch.setattr(pipeline, 'load_task', lambda name: run if name == 'ap' else downstream if name == 'ar_cash' else None)
    pipeline.run_tasks(conn, tmp_path / 'submission')
    assert observed == [('V100173', '26012023', 828850)]
    rows = [json.loads(line) for line in (tmp_path / 'submission/ap.jsonl').read_text().splitlines()]
    assert len(rows) == 2

def test_changed_unsafe_source_cannot_leave_a_stale_posting(conn, monkeypatch):
    from tasks import ap
    from tasks.ap_extract import extract_phase
    ap.run(conn)
    docs = extract_phase(conn, db.PHASES['dev'])
    docs[0]['issues'] = ['XML_PDF_MISMATCH']
    monkeypatch.setattr(ap, 'extract_phase', lambda *_: docs)
    with pytest.raises(ValueError, match='conflict'):
        ap.run(conn)

def test_all_requested_documents_are_published_and_decided(full_conn):
    from tasks.ap import run
    rows = run(full_conn)
    requested = {r[0] for r in full_conn.execute('SELECT id FROM task_ap_documents')}
    assert len(rows) == len(requested) == 305
    assert {r['doc_id'] for r in rows} == requested
    assert all(r['decision'] in {'POST', 'POST_PAYMENT_BLOCK', 'REJECT', 'HOLD', 'DUPLICATE', 'NOT_INVOICE'} for r in rows)
    assert full_conn.execute('SELECT COUNT(*) FROM ap_result WHERE decision IS NULL').fetchone()[0] == 0
    assert all(r['journal_entry'] is None for r in rows if r['decision'] not in {'POST', 'POST_PAYMENT_BLOCK'})

@pytest.mark.parametrize('doc_id,number,original', [
    ('API005197', '0009557', 'API004288'),
    ('API005200', 'F2611803', 'API004187'),
    ('API005206', '26030808', 'API003878'),
    ('API005210', '26012023', 'API004299'),
])
def test_resent_duplicates_publish_original_number(full_conn, doc_id, number, original):
    from tasks.ap import run
    rows = {r['doc_id']: r for r in run(full_conn)}
    row = rows[doc_id]
    assert (row['decision'], row['invoice_number'], row['duplicate_of']) == ('DUPLICATE', number, original)
    assert row['source_invoice_number'].startswith('F-')
    assert full_conn.execute('SELECT event_key FROM proposed_je WHERE event_key=?', ('ap:' + doc_id,)).fetchone() is None

def test_arithmetic_reject_preserves_reported_total_but_publishes_calculated_payable(full_conn):
    from tasks.ap import run
    row = next(r for r in run(full_conn) if r['doc_id'] == 'API005221')
    assert row['decision'] == 'REJECT'
    assert row['reasons'] == ['ARITHMETIC_ERROR']
    assert row['payable'] == 264496
    assert row['source_amounts']['payable'] == row['source_amounts']['gross'] == 308802
    assert row['representations']['xml'] == []
    assert row['journal_entry'] is None

def test_direct_debits_and_received_ic_invoices_are_posted(full_conn):
    from tasks.ap import run
    rows = {r['doc_id']: r for r in run(full_conn)}
    assert rows['API004187']['decision'] == 'POST'
    assert rows['API004187']['journal_entry']['lines'][-1]['assignment'] == 'F2611803'
    assert rows['API005161']['decision'] == 'POST'
    assert rows['API005161']['vendor_id'] == 'V-IC1000'
    assert rows['API005161']['journal_entry']['lines'][-1]['partner'] == 'V-IC1000'

def test_deposit_request_foreign_currency_and_credit_signs(full_conn):
    from tasks.ap import run
    rows = {r['doc_id']: r for r in run(full_conn)}
    deposit = rows['API004469']
    assert deposit['document_type'] == 'DOWN_PAYMENT_REQUEST'
    assert deposit['decision'] == 'POST'
    assert deposit['currency'] == 'EUR' and deposit['source_currency'] == 'USD'
    assert deposit['journal_entry']['lines'][0]['account'] == '40700000'
    assert rows['API005164']['currency'] == 'MXN'
    assert rows['API005164']['net'] > rows['API005164']['source_amounts']['net']
    assert rows['API005583']['net'] < 0
    assert rows['API005583']['decision'] == 'POST'

def test_non_invoice_actions_are_visible_without_journals(full_conn):
    from tasks.ap import run
    rows = {r['doc_id']: r for r in run(full_conn)}
    for doc_id, action in [('API005189', 'REGISTER_ALTERNATIVE_PAYEE'), ('API005195', 'UPDATE_BANK_DETAILS'), ('API005598', 'UPDATE_CONTRACTOR_CERTIFICATE'), ('API005592', 'NONE')]:
        assert rows[doc_id]['decision'] == 'NOT_INVOICE'
        assert rows[doc_id]['action'] == action
        assert rows[doc_id]['journal_entry'] is None

def test_po_missing_receipt_is_held_and_never_posted(full_conn):
    from tasks.ap import run
    full_conn.execute("DELETE FROM task_ap_documents WHERE id!='API004087'")
    full_conn.execute("DELETE FROM goods_receipts WHERE vendor=(SELECT vendor FROM purchase_orders WHERE id='4500018088')")
    row, = run(full_conn)
    assert row['decision'] == 'HOLD' and 'QTY_NOT_RECEIVED' in row['reasons']
    assert row['journal_entry'] is None
