"""Conciliación intragrupo (§6): un caso sintético por causa + regresión contra el golden de dev."""
import json

from tasks.ic import detect

AGR = {"loan": {"id": "KMI-2025-01", "principal": 500000000, "rate_bp": 600, "basis": "act/360", "lender": "1000", "borrower": "3100"}}
PAIRS = [["1000", "1100"], ["1000", "1200"], ["1000", "2100"], ["1000", "3100"], ["1100", "1910"]]


def L(entry, company, account, amount, partner=None, assignment=None, reference="", source="FI", date="2026-07-31", cc=None, amount_doc=None):
    return {"entry": entry, "company": company, "date": date, "reference": reference, "source": source, "account": account,
            "debit": max(amount, 0), "credit": max(-amount, 0), "partner": partner, "assignment": assignment, "cost_center": cc,
            "currency": "EUR", "amount_doc": abs(amount_doc if amount_doc is not None else amount)}


def run(ledger, received=(), pooling=()):
    return detect(ledger, AGR, PAIRS, "2026-07", set(received), list(pooling))


def by_cause(rows):
    return {(tuple(r["pair"]), r["cause"]): r for r in rows}


def lines(r):
    return sorted((l["company"], l["account"], l["debit"] - l["credit"], l.get("partner"), l.get("assignment"), l.get("cost_center"))
                  for l in r["adjustment"])


def issue(n, receiver, gross, net):
    return [L(f"1000-I{n}", "1000", "43300000", gross, receiver, f"IC1000-26-{n}", f"IC1000-26-{n}", "IC_BILLING"),
            L(f"1000-I{n}", "1000", "70500000", -net, source="IC_BILLING"), L(f"1000-I{n}", "1000", "47700000", net - gross, source="IC_BILLING")]


HIST_1200 = [L("1200-H", "1200", "40300000", -18058040, "V-IC1000", "IC1000-26-0027", "IC1000-26-0027", "AP", "2026-07-01"),
             L("1200-H", "1200", "62940000", 14924000, source="AP", date="2026-07-01", cc="CC-1200-ADM"),
             L("1200-H", "1200", "47200000", 3134040, source="AP", date="2026-07-01")]


def test_invoice_in_transit_accrued_by_receiver_with_its_usual_expense():
    rows = run(issue("0032", "1200", 18058040, 14924000) + HIST_1200)
    r = by_cause(rows)[(("1000", "1200"), "INVOICE_IN_TRANSIT")]
    assert r["responsible"] == "1200" and r["amount"] == 18058040
    assert lines(r) == [("1200", "40090000", -14924000, "1000", "IC1000-26-0032", None), ("1200", "62940000", 14924000, None, None, "CC-1200-ADM")]


def test_received_invoice_is_not_in_transit():
    assert run(issue("0032", "1200", 18058040, 14924000) + HIST_1200, received={"IC1000260032"}) == []


def test_unknown_reception_flags_no_transit():
    """Sin ap_result de P1 no se sabe qué llegó a la bandeja: mejor no marcar que marcar mal (test: IC1000-26-0041 sí llegó)."""
    assert detect(issue("0032", "1200", 18058040, 14924000) + HIST_1200, AGR, PAIRS, "2026-07", None, []) == []


def test_expense_taken_from_last_ap_invoice_not_from_a_payment():
    pay = [L("1200-F", "1200", "40300000", -5, "V-IC1000", "IC1000-26-0030", "F110-1200", "F110", "2026-07-20"),
           L("1200-F", "1200", "57200001", 5, source="F110", date="2026-07-20")]
    r = by_cause(run(issue("0032", "1200", 18058040, 14924000) + HIST_1200 + pay))[(("1000", "1200"), "INVOICE_IN_TRANSIT")]
    assert ("1200", "62940000", 14924000, None, None, "CC-1200-ADM") in lines(r)


def test_only_the_largest_unreceived_invoice_is_flagged():
    """Golden dev: de 4 facturas sin recibir solo marca una (la mayor). El resto se avisa para revisión manual."""
    rows = run(issue("0032", "1200", 18058040, 14924000) + issue("0034", "2100", 3411200, 3411200) + HIST_1200)
    assert [r["pair"] for r in rows if r["cause"] == "INVOICE_IN_TRANSIT"] == [["1000", "1200"]]


def test_interest_day_count_borrower_accrued_30_360():
    ledger = [L("1000-K", "1000", "55200000", 2583333, "3100", "KMI-2025-01", "KMI-INT-202607", "IC_LOAN"),
              L("1000-K", "1000", "76210000", -2583333, source="IC_LOAN"),
              L("3100-K", "3100", "66210000", 47251000, reference="KMI-INT-202607", source="IC_LOAN", amount_doc=2500000),
              L("3100-K", "3100", "55200000", -47251000, "1000", "KMI-2025-01", "KMI-INT-202607", "IC_LOAN", amount_doc=2500000)]
    r = by_cause(run(ledger))[(("1000", "3100"), "INTEREST_DAY_COUNT")]
    assert r["responsible"] == "3100" and r["amount"] == 83333
    assert lines(r) == [("3100", "55200000", -1575027, "1000", "KMI-2025-01", None), ("3100", "66210000", 1575027, None, None, None)]


def test_no_interest_booked_is_not_a_day_count_difference():
    assert run([]) == []


def test_wrong_trading_partner_on_pooling_sweep():
    ledger = [L("1000-P", "1000", "55200000", -14415889, "1100", reference="CP2607281100", source="POOL"),
              L("1100-P", "1100", "55200000", 14415889, "1200", reference="CP2607281100", source="POOL")]
    r = by_cause(run(ledger))[(("1000", "1100"), "WRONG_TRADING_PARTNER")]
    assert r["responsible"] == "1100"
    assert lines(r) == [("1100", "55200000", -14415889, "1200", None, None), ("1100", "55200000", 14415889, "1000", None, None)]


def test_duplicate_posting_reverses_the_later_entry():
    def inv(e, date):
        return [L(e, "2100", "40300000", -3411200, "V-IC1000", "IC1000-26-0024", "IC1000-26-0024", "AP", date),
                L(e, "2100", "62940000", 3411200, source="AP", date=date, cc="CC-2100-ADM")]
    r = by_cause(run(inv("2100-A", "2026-06-01") + inv("2100-B", "2026-07-03")))[(("1000", "2100"), "DUPLICATE_POSTING")]
    assert r["responsible"] == "2100" and r["amount"] == 3411200
    assert lines(r) == [("2100", "40300000", 3411200, "V-IC1000", "IC1000-26-0024", None), ("2100", "62940000", -3411200, None, None, "CC-2100-ADM")]


def test_pooling_not_booked_comes_from_bank_without_adjustment():
    r = by_cause(run([], pooling=[{"company": "1200", "amount": -27053177, "ref1": "CP2607221200"}]))[(("1000", "1200"), "POOLING_NOT_BOOKED")]
    assert r["adjustment"] == [] and r["responsible"] == "1200" and r["amount"] == 27053177


def test_dev_score_against_golden(tmp_path):
    from common import db
    from tasks import bank_rec, ic
    import score
    conn = db.build_db(db.PHASES["dev"], tmp_path / "dev.db")
    gold_ap = [json.loads(l) for l in open(db.PHASES["dev"] / "golden/ap.jsonl")]  # simula a P1
    conn.executemany("INSERT INTO ap_result(doc_id, company, vendor_id, invoice_number, decision) VALUES (?, ?, ?, ?, ?)",
                     [(r["doc_id"], r.get("company"), r.get("vendor_id"), r.get("invoice_number"), r["decision"]) for r in gold_ap])
    bank_rec.run(conn)
    rows = ic.run(conn)
    gold = [json.loads(l) for l in open(db.PHASES["dev"] / "golden/ic.jsonl")]
    s, detail = score.score_ic(gold, rows)
    assert s >= 0.999, (detail, [(r["pair"], r["cause"]) for r in rows])
