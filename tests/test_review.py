"""Casos dudosos: regla → decisión de la IA versionada (confianza ≥ 0.8) → si no, opción prudente y queda marcado como duda."""
import json
import sqlite3

from common import db, review


def conn_with(decisions, tmp_path):
    c = sqlite3.connect(":memory:")
    c.executescript(db.SHARED)
    f = tmp_path / "review.jsonl"
    f.write_text("".join(json.dumps(d) + "\n" for d in decisions))
    review.load(c, f)
    return c


def test_confident_valid_decision_is_used_and_not_a_doubt(tmp_path):
    c = conn_with([{"key": "bank:BL1", "decision": "BANK_FEE_NOT_BOOKED", "confidence": 0.9, "reason": "comisión"}], tmp_path)
    assert review.decide(c, "bank:BL1", "bank_rec", {"text": "X"}, ["BANK_FEE_NOT_BOOKED", "BANK_ERROR"], "BANK_ERROR") == "BANK_FEE_NOT_BOOKED"
    assert c.execute("SELECT COUNT(*) FROM doubt").fetchone()[0] == 0


def test_low_confidence_unknown_option_or_duda_falls_back_and_is_marked(tmp_path):
    c = conn_with([{"key": "a", "decision": "BANK_FEE_NOT_BOOKED", "confidence": 0.5}, {"key": "b", "decision": "INVENTADA", "confidence": 1},
                   {"key": "c", "decision": "DUDA", "confidence": 1}], tmp_path)
    for k in ("a", "b", "c", "d"):
        assert review.decide(c, k, "bank_rec", {"text": k}, ["BANK_FEE_NOT_BOOKED", "BANK_ERROR"], "BANK_ERROR") == "BANK_ERROR"
    rows = c.execute("SELECT key, task, evidence, options, fallback FROM doubt ORDER BY key").fetchall()
    assert [r[0] for r in rows] == ["a", "b", "c", "d"]
    assert json.loads(rows[0][2]) == {"text": "a"} and json.loads(rows[0][3]) == ["BANK_FEE_NOT_BOOKED", "BANK_ERROR"] and rows[0][4] == "BANK_ERROR"


def test_missing_cache_file_means_no_decisions(tmp_path):
    c = sqlite3.connect(":memory:")
    c.executescript(db.SHARED)
    review.load(c, tmp_path / "no_existe.jsonl")
    assert review.decide(c, "k", "t", {}, ["X"], "Y") == "Y"
