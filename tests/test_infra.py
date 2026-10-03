import json
import sqlite3

import pytest

import run
from common import db
from common.je import make_je, propose, norm_num


# ---------------------------------------------------------------- fixture: a tiny phase dir
def _jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n")


@pytest.fixture
def phase(tmp_path):
    p = tmp_path / "phase_x"
    _jsonl(p / "erp/vendors.jsonl", [{"id": "V1", "name": "Á", "bank": {"iban": "ES1"}, "natural_person": False},
                                     {"id": "V2", "name": "B", "extra": 7}])
    _jsonl(p / "erp/journal_entries.jsonl", [{"id": "1000-2026-1", "company": "1000", "doc_type": "ZP", "posting_date": "2026-07-01",
                                              "document_date": "2026-07-01", "reference": "R", "header_text": "H", "source": "FI", "currency": "EUR",
                                              "lines": [{"line": 1, "account": "57200001", "debit": 0, "credit": 500, "partner": None},
                                                        {"line": 2, "account": "41000000", "debit": 500, "credit": 0, "partner": "V1"}]}])
    _jsonl(p / "bank/BIN-1000/2026-07.lines.jsonl", [{"bank_line": "BL1", "booking_date": "2026-07-01", "amount": -500, "text": "X"}])
    (p / "erp/companies.json").write_text(json.dumps([{"code": "1000", "name": "Holding"}]))
    (p / "erp/tax_codes.json").write_text(json.dumps({"tax_codes": {"S21": 21}}))
    (p / "tasks").mkdir()
    (p / "tasks/ap_documents.json").write_text(json.dumps(["API1", "API2"]))
    (p / "tasks/close.json").write_text(json.dumps({"month": "2026-07", "steps": ["ACCRUAL"]}))
    return p


@pytest.fixture
def conn(phase, tmp_path):
    return db.build_db(phase, tmp_path / "x.db")


# ---------------------------------------------------------------- journal entries
def test_make_je_returns_normalized_balanced_entry():
    je = make_je("1100", [{"account": "62600000", "debit": 300}, {"account": "57200001", "credit": 300}])
    assert je == {"company": "1100", "lines": [
        {"account": "62600000", "debit": 300, "credit": 0, "partner": None, "cost_center": None, "wbs": None},
        {"account": "57200001", "debit": 0, "credit": 300, "partner": None, "cost_center": None, "wbs": None}]}


def test_make_je_rejects_unbalanced():
    with pytest.raises(ValueError, match="cuadra"):
        make_je("1100", [{"account": "62600000", "debit": 300}, {"account": "57200001", "credit": 299}])


def test_make_je_rejects_line_with_debit_and_credit():
    with pytest.raises(ValueError):
        make_je("1100", [{"account": "62600000", "debit": 1, "credit": 1}])


def test_make_je_rejects_cost_center_and_wbs_together():
    with pytest.raises(ValueError, match="cost_center"):
        make_je("1100", [{"account": "62600000", "debit": 1, "cost_center": "CC", "wbs": "W"}, {"account": "57200001", "credit": 1}])


def test_make_je_rejects_non_integer_amounts():
    with pytest.raises(ValueError):
        make_je("1100", [{"account": "62600000", "debit": 1.5}, {"account": "57200001", "credit": 1.5}])


def test_make_je_balances_per_company_on_intercompany_lines():
    lines = [{"company": "1000", "account": "55200000", "debit": 10}, {"company": "1200", "account": "55200000", "credit": 10}]
    with pytest.raises(ValueError, match="1000"):
        make_je("1000", lines)
    ok = make_je("1000", lines + [{"company": "1000", "account": "57200001", "credit": 10}, {"company": "1200", "account": "57200001", "debit": 10}])
    assert ok["lines"][1]["company"] == "1200"


def test_norm_num_is_the_scorer_normalization():
    assert norm_num("2026/322") == norm_num("2026-322") == "2026322"
    assert norm_num("0007350") == "7350"


# ---------------------------------------------------------------- database
def test_build_db_loads_every_source(conn):
    assert conn.execute("select count(*) from vendors").fetchone()[0] == 2
    assert json.loads(conn.execute("select bank from vendors where id='V1'").fetchone()[0]) == {"iban": "ES1"}
    assert conn.execute("select extra from vendors where id='V2'").fetchone()[0] == 7
    assert conn.execute("select name from companies").fetchone()[0] == "Holding"
    assert db.get_json(conn, "erp/tax_codes") == {"tax_codes": {"S21": 21}}
    assert db.get_json(conn, "tasks/close")["month"] == "2026-07"
    assert [r[0] for r in conn.execute("select id from task_ap_documents")] == ["API1", "API2"]


def test_build_db_flattens_journal_lines_with_book_line_id(conn):
    row = conn.execute("select company, posting_date, reference, account, debit, partner from je_line where line_id='1000-2026-1#2'").fetchone()
    assert tuple(row) == ("1000", "2026-07-01", "R", "41000000", 500, "V1")


def test_build_db_loads_bank_lines_with_account_and_month(conn):
    row = conn.execute("select account, month, amount from bank_line where bank_line='BL1'").fetchone()
    assert tuple(row) == ("BIN-1000", "2026-07", -500)


def test_rebuild_keeps_llm_extraction_cache(phase, tmp_path):
    c = db.build_db(phase, tmp_path / "x.db")
    c.execute("insert into doc_extract(doc_id, source, data) values ('API1', 'llm', '{}')")
    c.commit()
    c.close()
    c = db.build_db(phase, tmp_path / "x.db")
    assert c.execute("select source from doc_extract").fetchone()[0] == "llm"
    assert c.execute("select count(*) from vendors").fetchone()[0] == 2


# ---------------------------------------------------------------- shared run state
def test_propose_refuses_the_same_event_twice(conn):
    je = make_je("1000", [{"account": "62600000", "debit": 9}, {"account": "57200001", "credit": 9}])
    propose(conn, "bank:BL1", "P2", "bank_rec", je)
    with pytest.raises(sqlite3.IntegrityError):
        propose(conn, "bank:BL1", "P3", "ar_cash", je)


def test_ledger_is_recorded_journal_plus_proposals(conn):
    propose(conn, "bank:BL1", "P2", "bank_rec", make_je("1000", [{"account": "62600000", "debit": 9}, {"account": "57200001", "credit": 9}]))
    bal = dict(conn.execute("select account, sum(debit - credit) from ledger where company='1000' group by account"))
    assert bal == {"57200001": -509, "41000000": 500, "62600000": 9}


def test_bank_line_can_only_be_explained_once(conn):
    conn.execute("insert into bank_explained(bank_line, account, kind, owner) values ('BL1', 'BIN-1000', 'MATCH', 'P2')")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("insert into bank_explained(bank_line, account, kind, owner) values ('BL1', 'BIN-1000', 'ADJ', 'P3')")


def test_reset_run_clears_run_state_but_not_cache(conn):
    conn.execute("insert into doc_extract(doc_id, source, data) values ('API1', 'parser', '{}')")
    propose(conn, "k", "P1", "ap", make_je("1000", [{"account": "6", "debit": 1}, {"account": "4", "credit": 1}]))
    db.reset_run(conn)
    assert conn.execute("select count(*) from proposed_je").fetchone()[0] == 0
    assert conn.execute("select count(*) from doc_extract").fetchone()[0] == 1


# ---------------------------------------------------------------- runner
def test_run_writes_one_jsonl_per_task_and_skips_missing_modules(conn, tmp_path, monkeypatch):
    def fake(name):
        if name == "ap":
            return lambda c: [{"doc_id": "API1", "decision": "POST"}]
        return None
    monkeypatch.setattr(run, "load_task", fake)
    out = tmp_path / "sub"
    run.run_tasks(conn, out)
    assert sorted(p.name for p in out.iterdir()) == sorted(f"{t}.jsonl" for t in run.TASKS)
    assert json.loads((out / "ap.jsonl").read_text()) == {"doc_id": "API1", "decision": "POST"}
    assert (out / "close.jsonl").read_text() == ""


def test_a_crashing_task_does_not_block_the_others(conn, tmp_path, monkeypatch):
    def boom(c):
        raise RuntimeError("bug de un compañero")
    monkeypatch.setattr(run, "load_task", lambda n: boom if n == "ap" else (lambda c: [{"x": n}]))
    out = tmp_path / "sub"
    run.run_tasks(conn, out)
    assert (out / "ap.jsonl").read_text() == ""
    assert json.loads((out / "close.jsonl").read_text()) == {"x": "close"}


def test_rebuild_reloads_extraction_cache_shared_through_git(phase, tmp_path, monkeypatch):
    monkeypatch.setattr(db, "CACHE", tmp_path / "cache")
    c = db.build_db(phase, tmp_path / "a.db")
    c.execute("insert into doc_extract values ('API1', 'llm', 0.9, '{\"n\": 1}')")
    db.dump_cache(c, phase)
    fresh = db.build_db(phase, tmp_path / "teammate.db")  # otro compañero, otra base
    assert fresh.execute("select source, confidence, data from doc_extract").fetchall() == [("llm", 0.9, '{"n": 1}')]


def test_consistency_flags_entries_written_but_not_proposed(conn):
    je = make_je("1000", [{"account": "62600000", "debit": 9}, {"account": "57200001", "credit": 9}])
    rows = {"bank_rec": [{"account": "BIN-1000", "company": "1000", "adjustments": [{"category": "BANK_FEE_NOT_BOOKED", "lines": je["lines"]}]}]}
    assert run.inconsistencies(conn, rows) == {("1000", "62600000"): 9, ("1000", "57200001"): -9}
    propose(conn, "bank:BL1", "P2", "bank_rec", je)
    assert run.inconsistencies(conn, rows) == {}


# ---------------------------------------------------------------- tipo de cambio SYN-BCE (una sola búsqueda para AP, banco y cierre)
def _rates():
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE fx_rates(date, base, currency, rate, source)")
    c.executemany("INSERT INTO fx_rates VALUES (?, ?, ?, ?, 'SYN-BCE')", [("2026-07-09", "EUR", "USD", 1.23), ("2026-07-10", "EUR", "USD", 1.2344),
                                                                         ("2026-07-10", "USD", "USD", 9.99)])
    return c


def test_fx_rate_is_the_day_or_last_published_eur_based():
    c = _rates()
    assert db.fx_rate(c, "EUR", "2026-07-10") == 1.0
    assert db.fx_rate(c, "USD", "2026-07-10") == 1.2344             # base EUR; la fila base USD no cuenta
    assert db.fx_rate(c, "USD", "2026-07-12") == 1.2344             # fin de semana: último publicado
    assert db.fx_rate(c, "USD", "2026-07-09T23:00:00") == 1.23      # acepta fecha con hora


def test_fx_rate_missing_is_an_explicit_error_code():
    with pytest.raises(ValueError, match="^FX_RATE_MISSING$"):     # AP lo usa como motivo HOLD
        db.fx_rate(_rates(), "USD", "2026-07-08")


# ---------------------------------------------------------------- ruta de la fase: guardada al construir, no adivinada por el mes
def test_phase_dir_is_the_built_directory(conn, phase):
    assert db.phase_dir(conn) == phase


def test_connect_backfills_phase_dir_in_databases_built_before_it_existed(phase, tmp_path, monkeypatch):
    monkeypatch.setattr(db, "ROOT", tmp_path)
    monkeypatch.setitem(db.PHASES, "x", phase)
    old = db.build_db(phase, tmp_path / "db" / "kalmora_x.db")
    old.execute("DELETE FROM json_files WHERE name = 'phase/dir'")
    old.commit()
    old.close()
    assert db.phase_dir(db.connect("x")) == phase
