"""P1/P3 contract: source-backed fee journal and duplicate suppression."""
import json
import pytest
from common import db

@pytest.fixture
def conn(tmp_path):
    c = db.build_db(db.PHASES['dev'], tmp_path / 'ap.db')
    c.execute("DELETE FROM task_ap_documents WHERE id NOT IN ('API004299', 'API005210')")
    yield c
    c.close()

def test_fee_posts_supplier_assignment_and_shared_decisions(conn):
    from tasks.ap import run
    rows = {r['doc_id']: r for r in run(conn)}
    assert rows['API004299']['decision'] == 'POST'
    assert rows['API005210']['decision'] == 'DUPLICATE'
    assert rows['API005210']['duplicate_of'] == 'API004299'
    assert rows['API005210']['journal_entry'] is None
    assert conn.execute("SELECT doc_id, vendor_id, invoice_number, decision FROM ap_result ORDER BY doc_id").fetchall() == [
        ('API004299', 'V100173', '26012023', 'POST'),
        ('API005210', 'V100173', 'F-26012023', 'DUPLICATE')]
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

@pytest.mark.parametrize('change', [
    {'issues': ['XML_PDF_MISMATCH']}, {'currency': 'USD'}, {'iban': 'OTHER'},
    {'gross': 1}, {'withholding': 1}, {'po_refs': ['PO']},
])
def test_unsupported_or_unsafe_original_stays_pending(conn, monkeypatch, change):
    from tasks import ap
    from tasks.ap_extract import extract_phase
    # Isolate the unsafe original: changing currency/amount makes a different
    # duplicate key, so a separate valid submission need not be rejected.
    docs = extract_phase(conn, db.PHASES['dev'])[:1]
    docs[0].update(change)
    monkeypatch.setattr(ap, 'extract_phase', lambda *_: docs)
    ap.run(conn)
    assert conn.execute("SELECT decision FROM ap_result WHERE doc_id='API004299'").fetchone()[0] is None
    assert conn.execute("SELECT COUNT(*) FROM proposed_je").fetchone()[0] == 0

def test_missing_cost_evidence_does_not_guess(conn):
    from tasks.ap import run
    conn.execute("DELETE FROM je_line WHERE account='62300000'")
    run(conn)
    assert conn.execute("SELECT decision FROM ap_result WHERE doc_id='API004299'").fetchone()[0] is None
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
