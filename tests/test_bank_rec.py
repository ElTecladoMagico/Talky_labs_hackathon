"""Conciliación bancaria: un caso sintético por excepción de la §4 + regresión contra el golden de dev."""
import json
from types import SimpleNamespace

import pytest

from tasks.bank_rec import reconcile


# ---------------------------------------------------------------- builders
def B(id, amount, text="", date="2026-07-10", ref1="", ref2="", detail=""):
    return {"bank_line": id, "booking_date": date, "amount": amount, "text": text, "ref1": ref1, "ref2": ref2, "detail": detail or text}


def K(id, amount, date="2026-07-10", reference="", header="", source="FI", lines=None):
    return {"id": id, "entry": id.split("#")[0], "date": date, "amount": amount, "reference": reference, "header": header,
            "source": source, "lines": lines or []}


def acc(bank=(), book=(), id="BIN-1100", company="1100", gl="57200001", currency="EUR", prev_bank=(), prev_book=()):
    return {"id": id, "company": company, "gl": gl, "currency": currency, "lc": "EUR" if company != "3100" else "MXN",
            "bank": list(bank), "book": list(book), "prev_bank": list(prev_bank), "prev_book": list(prev_book)}


def ctx(**kw):
    base = dict(ap={}, vendor_acc={}, receipt_customer={}, factoring={}, rate=lambda cur, date: 1.0, decide=lambda key, ev, opts, fb: fb)
    return SimpleNamespace(**(base | kw))


def one(rows, account="BIN-1100"):
    return next(r for r in rows if r["account"] == account)


def cats(row):
    return {x.get("bank_line") or x.get("book_line"): x["category"] for x in row["unmatched_bank"] + row["unmatched_book"]}


def adj(row, category):
    return [a for a in row["adjustments"] if a["category"] == category]


def lines(a):
    return sorted((l["account"], l["debit"] - l["credit"], l.get("partner"), l.get("assignment"), l.get("cost_center")) for l in a["lines"])


# ---------------------------------------------------------------- casación
def test_exact_match_prefers_the_linked_reference():
    r = one(reconcile([acc([B("b1", -500, ref2="F-2026-0002")], [K("e1#1", -500, reference="F-2026-0001"), K("e2#1", -500, reference="F-2026-0002")])], ctx()))
    assert r["matches"] == [{"bank_lines": ["b1"], "book_lines": ["e2#1"]}]
    assert cats(r) == {"e1#1": "OUTSTANDING_PAYMENT"}


def test_remittance_one_bank_line_many_book_lines_by_reference():
    bank = [B("b1", -300, "ORDEN TRANSFERENCIAS SEPA REMESA", ref1="20260710-433")]
    book = [K(f"e{i}#1", -100, reference="F110-1100-20260710-433") for i in range(3)]
    r = one(reconcile([acc(bank, book)], ctx()))
    assert r["matches"] == [{"bank_lines": ["b1"], "book_lines": ["e0#1", "e1#1", "e2#1"]}]


def test_payroll_in_two_batches_against_one_book_line():
    bank = [B("b1", -70, "ORDEN NOMINAS 07/2026 LOTE 1", "2026-07-31"), B("b2", -30, "ORDEN NOMINAS 07/2026 LOTE 2", "2026-07-31")]
    r = one(reconcile([acc(bank, [K("e1#2", -100, "2026-07-31", reference="NOM202607")])], ctx()))
    assert r["matches"] == [{"bank_lines": ["b1", "b2"], "book_lines": ["e1#2"]}]


def test_foreign_transfer_matched_with_fx_difference():
    """668/768 según la diferencia realizada total: línea del proveedor del pago (valor de la factura) frente al banco (golden: GBP → 768)."""
    pay = lambda v, inv, amt: [{"account": "41000000", "debit": amt, "credit": 0, "partner": v, "assignment": inv}]
    bank = [B("b1", -195243, "TRANSF. EXTERIOR USD 2,400.00", ref2="0035252"), B("b2", -5743000, "TRANSF. EXTERIOR GBP", ref2="26026284")]
    book = [K("e1#2", -194426, reference="0035252", source="SWIFT", lines=pay("V135", "0035252", 192771)),
            K("e2#2", -5718981, reference="26026284", source="SWIFT", lines=pay("V141", "26026284", 5754155))]
    r = one(reconcile([acc(bank, book, id="BIN-1000", company="1000")], ctx()), "BIN-1000")
    assert len(r["matches"]) == 2 and not r["unmatched_bank"]
    fx = adj(r, "FX_RATE_DIFFERENCE")
    assert sorted(lines(a) for a in fx) == sorted([[("57200001", -817, None, None, None), ("66800000", 817, None, None, None)],
                                                    [("57200001", -24019, None, None, None), ("76800000", 24019, None, None, None)]])


def test_loan_instalment_matched_and_interest_booked():
    bank = [B("b1", -11511250, "CUOTA PRESTAMO 0182-445 RECIBO 07/2026", ref1="0182445")]
    book = [K("e1#2", -10000000, header="Cuota préstamo maquinaria 0182-445 07/2026", reference="PRE202607", source="LOAN")]
    r = one(reconcile([acc(bank, book)], ctx()))
    assert r["matches"] == [{"bank_lines": ["b1"], "book_lines": ["e1#2"]}]
    assert lines(adj(r, "LOAN_INTEREST_NOT_BOOKED")[0]) == [("57200001", -1511250, None, None, None), ("66200000", 1511250, None, None, None)]


def test_book_amount_error_corrected_against_vendor():
    entry = [{"account": "40000000", "debit": 1000, "credit": 0, "partner": "V1", "assignment": "F-2026-7"},
             {"account": "57200001", "debit": 0, "credit": 1000}]
    r = one(reconcile([acc([B("b1", -1100, "TRANSFERENCIA A X", ref2="F-2026-7")], [K("e1#2", -1000, reference="F-2026-7", lines=entry)])], ctx()))
    assert len(r["matches"]) == 1 and cats(r) == {"e1#2": "BOOK_AMOUNT_ERROR"}  # §4: categoría de libro, y el cargo queda casado
    assert lines(adj(r, "BOOK_AMOUNT_ERROR")[0]) == [("40000000", 100, "V1", "F-2026-7", None), ("57200001", -100, None, None, None)]


def test_book_amount_error_linked_by_beneficiary_name():
    """Test (BLC-2100): dígitos traspuestos (56.366,55 en libro, 56.365,65 en banco) y sin referencia común: enlaza el beneficiario."""
    entry = [{"account": "40000000", "debit": 5636655, "credit": 0, "partner": "V9", "assignment": "AGC26/1"},
             {"account": "57200004", "debit": 0, "credit": 5636655}]
    bank = [B("b1", -5636565, "TRANSFERENCIA A ENGENHARIA E CONSTRUÇÃO MÉND", ref2="PAGO FRAS AGC26/")]
    book = [K("e1#2", -5636655, reference="F110-2100-20260910-473", header="Pago F110-2100-20260910-473 – Engenharia e Construção Méndez", lines=entry)]
    r = one(reconcile([acc(bank, book, id="BLC-2100", company="2100", gl="57200004")], ctx()), "BLC-2100")
    assert r["matches"] == [{"bank_lines": ["b1"], "book_lines": ["e1#2"]}] and cats(r) == {"e1#2": "BOOK_AMOUNT_ERROR"}
    assert lines(r["adjustments"][0]) == [("40000000", -90, "V9", "AGC26/1", None), ("57200004", 90, None, None, None)]


def test_name_link_needs_same_sign_and_small_difference():
    bank = [B("b1", -400000, "TRANSFERENCIA A ENGENHARIA E CONSTRUÇÃO MÉND")]
    book = [K("e1#2", -5636655, header="Pago Engenharia e Construção Méndez", source="F110")]
    r = one(reconcile([acc(bank, book)], ctx()))
    assert r["matches"] == []


def test_factoring_advance_net_of_charges_books_665():
    bank = [B("b1", 38267830, "ABONO ANTICIPO FACTORING REMESA FAC1")]
    book = [K("e1#1", 38267830, reference="FAC1", source="FACTORING", header="Anticipo factoring FAC1")]
    fac = {"FAC1": [{"invoice": "OB-48", "advance": 38818623, "interest": 442963, "fee": 107830}]}
    r = one(reconcile([acc(bank, book, id="BAE-1100", gl="57200003")], ctx(factoring=fac)), "BAE-1100")
    assert len(r["matches"]) == 1
    assert lines(adj(r, "FACTORING_CHARGES_NOT_BOOKED")[0]) == [("55300000", -550793, "FACTOR-BAE", "OB-48", None),
                                                               ("66500000", 550793, None, None, None)]


def test_prior_month_open_book_item_clears_this_month():
    """Test ago: el pago URG07 quedó pendiente el 31/07 y sale en el banco el 03/08 → se casa con el asiento de julio."""
    a = acc([B("b1", -7011700, "TRANSFERENCIA A PEÑA Y RIBAS ENCOFRADOS", "2026-08-03")],
            prev_book=[K("u1#2", -7011700, "2026-07-31", reference="URG07", source="MANUAL_PAYMENT"),
                       K("x1#2", -500, "2026-07-30", reference="R")],
            prev_bank=[B("j1", -500, "PAGO", "2026-07-30")])
    r = one(reconcile([a], ctx()))
    assert r["matches"] == [{"bank_lines": ["b1"], "book_lines": ["u1#2"]}] and not r["unmatched_bank"]


def test_prior_month_after_the_fact_fee_entry_is_not_an_open_item():
    """Dev: tesorería registra el 30/06 la comisión del 10/06; no puede absorber la comisión igual del 10/07."""
    a = acc([B("b1", -3200, "COMISION TRANSFERENCIA EXTERIOR OUR", "2026-07-10")],
            prev_book=[K("f1#2", -3200, "2026-06-30", reference="COMISION", source="BANKFEE")],
            prev_bank=[B("j1", -3200, "COMISION TRANSFERENCIA EXTERIOR OUR", "2026-06-10")])
    r = one(reconcile([a], ctx()))
    assert r["matches"] == [] and cats(r) == {"b1": "BANK_FEE_NOT_BOOKED"}


def test_prior_month_book_item_already_in_prior_statement_is_not_reused():
    a = acc([B("b1", -500, "PAGO", "2026-08-02")], prev_book=[K("x1#2", -500, "2026-07-30", reference="R")],
            prev_bank=[B("j1", -500, "PAGO", "2026-07-30")])
    assert one(reconcile([a], ctx()))["matches"] == []


# ---------------------------------------------------------------- banco sin casar
DD = "RECIBO AGUAS DE VEGALTA REF. MANDATO V100046-1100 FRA 0023956"


def test_direct_debit_with_posted_invoice_is_booked_to_vendor():
    c = ctx(ap={("1100", "V100046", "23956"): "0023956"}, vendor_acc={"V100046": "41000000"})
    r = one(reconcile([acc([B("b1", -86707, "RECIBO AGUAS DE VEGALTA", detail=DD, ref2="0023956")], gl="57200002", id="CMA-1100")], c), "CMA-1100")
    assert cats(r) == {"b1": "DIRECT_DEBIT_NOT_BOOKED"}
    assert lines(adj(r, "DIRECT_DEBIT_NOT_BOOKED")[0]) == [("41000000", 86707, "V100046", "0023956", None),
                                                          ("57200002", -86707, None, None, None)]


def test_direct_debit_of_an_invoice_posted_in_another_company_is_not_booked():
    """Dev con P1: 2026-037570 contabilizada en 1910 pero el recibo (mandato V100028-1100) carga en CMA-1100 → destinatario erróneo."""
    c = ctx(ap={("1910", "V100046", "23956"): "0023956"}, vendor_acc={"V100046": "41000000"})
    r = one(reconcile([acc([B("b1", -86707, "RECIBO AGUAS DE VEGALTA", detail=DD, ref2="0023956")])], c))
    assert cats(r) == {"b1": "DIRECT_DEBIT_NOT_BOOKED"} and r["adjustments"] == []


def test_direct_debit_without_posted_invoice_is_classified_but_not_booked():
    """Golden dev: el recibo de una factura rechazada (o no recibida) se clasifica pero no se asienta."""
    r = one(reconcile([acc([B("b1", -86707, "RECIBO AGUAS DE VEGALTA", detail=DD, ref2="0023956")])], ctx(vendor_acc={"V100046": "41000000"})))
    assert cats(r) == {"b1": "DIRECT_DEBIT_NOT_BOOKED"} and r["adjustments"] == []


def test_duplicated_bank_charge_is_bank_error_and_not_booked_twice():
    c = ctx(ap={("1100", "V100046", "23956"): "0023956"}, vendor_acc={"V100046": "41000000"})
    bank = [B("b1", -86707, "RECIBO AGUAS", "2026-07-13", "R1", "0023956", DD), B("b2", -86707, "RECIBO AGUAS", "2026-07-14", "R1", "0023956", DD)]
    r = one(reconcile([acc(bank)], c))
    assert cats(r) == {"b1": "DIRECT_DEBIT_NOT_BOOKED", "b2": "BANK_ERROR"}
    assert len(r["adjustments"]) == 1


def test_bank_reversing_its_own_duplicate_is_bank_error_not_a_receipt():
    """Test ago: «ANULACION CARGO DUPLICADO» devuelve el cargo duplicado de julio; no es un cobro de cliente."""
    r = one(reconcile([acc([B("b1", 526544, "ANULACION CARGO DUPLICADO 275173258792", "2026-08-06")])], ctx()))
    assert cats(r) == {"b1": "BANK_ERROR"} and r["adjustments"] == []


def test_unknown_text_asks_the_reviewer_and_applies_its_decision():
    asked = {}

    def decide(key, ev, opts, fb):
        asked.update(key=key, ev=ev, opts=opts, fb=fb)
        return "BANK_FEE_NOT_BOOKED"
    r = one(reconcile([acc([B("b1", -1500, "CARGO SERVICIO BANCA ONLINE", detail="CARGO SERVICIO BANCA ONLINE TRIM")])], ctx(decide=decide)))
    assert asked["key"] == "bank:b1" and asked["fb"] == "BANK_ERROR" and "BANK_FEE_NOT_BOOKED" in asked["opts"]
    assert asked["ev"]["detail"] == "CARGO SERVICIO BANCA ONLINE TRIM" and asked["ev"]["account"] == "BIN-1100"
    assert cats(r) == {"b1": "BANK_FEE_NOT_BOOKED"} and lines(r["adjustments"][0]) == [("57200001", -1500, None, None, None), ("62600000", 1500, None, None, None)]


def test_unknown_text_without_decision_is_prudent_no_adjustment():
    r = one(reconcile([acc([B("b1", -1500, "CARGO SERVICIO BANCA ONLINE")])], ctx()))
    assert cats(r) == {"b1": "BANK_ERROR"} and r["adjustments"] == []


def test_unknown_credit_is_a_doubt_not_an_automatic_receipt():
    """Solo «TRANSFERENCIA DE…/COBRO…» es cobro no importado por regla; otro abono raro se pregunta (prudente: sin asiento)."""
    r = one(reconcile([acc([B("b1", 900, "ABONO VARIOS 0001")]), ], ctx()))
    assert cats(r) == {"b1": "BANK_ERROR"} and r["adjustments"] == []


def test_fees_grouped_by_day_text_amount_and_guarantee_fees_to_669():
    bank = [B("b1", -3200, "COMISION TRANSFERENCIA EXTERIOR OUR"), B("b2", -3200, "COMISION TRANSFERENCIA EXTERIOR OUR"),
            B("b3", -950, "GASTOS SWIFT"), B("b4", -5000, "COMISION AVALES TECNICOS")]
    r = one(reconcile([acc(bank)], ctx()))
    assert set(cats(r).values()) == {"BANK_FEE_NOT_BOOKED"}
    got = sorted(lines(a) for a in adj(r, "BANK_FEE_NOT_BOOKED"))
    assert got == sorted([[("57200001", -6400, None, None, None), ("62600000", 6400, None, None, None)],
                          [("57200001", -950, None, None, None), ("62600000", 950, None, None, None)],
                          [("57200001", -5000, None, None, None), ("66900000", 5000, None, None, None)]])


def test_usd_account_fee_converted_to_company_currency():
    a = acc([B("b1", -1800, "COMISION TRANSFERENCIA EXTERIOR OUR")], id="BANH-3100-USD", company="3100", gl="57200006", currency="USD")
    r = one(reconcile([a], ctx(rate=lambda cur, d: {"USD": 1.2344, "MXN": 19.0053}[cur])), "BANH-3100-USD")
    assert lines(r["adjustments"][0]) == [("57200006", -27713, None, None, None), ("62600000", 27713, None, None, None)]


def test_interest_and_its_withholding_are_one_adjustment():
    bank = [B("b1", 403000, "ABONO LIQUIDACION INTERESES", "2026-07-31"), B("b2", -76570, "RETENCION 19% S/ INTERESES", "2026-07-31")]
    r = one(reconcile([acc(bank)], ctx()))
    assert cats(r) == {"b1": "INTEREST_NOT_BOOKED", "b2": "INTEREST_NOT_BOOKED"}
    assert lines(r["adjustments"][0]) == [("47300000", 76570, None, None, None), ("57200001", 326430, None, None, None),
                                          ("76200000", -403000, None, None, None)]


def test_loan_interest_charge_without_book_entry():
    r = one(reconcile([acc([B("b1", -250000, "LIQ INTERESES PRESTAMO SINDICADO")])], ctx()))
    assert cats(r) == {"b1": "LOAN_INTEREST_NOT_BOOKED"}
    assert lines(r["adjustments"][0]) == [("57200001", -250000, None, None, None), ("66200000", 250000, None, None, None)]


def test_card_settlement():
    r = one(reconcile([acc([B("b1", -1180600, "LIQUIDACION TARJETA VISA EMPRESA 4598")], id="CMA-1000", company="1000", gl="57200002")], ctx()), "CMA-1000")
    assert lines(r["adjustments"][0]) == [("57200002", -1180600, None, None, None), ("62910000", 1180600, None, None, "CC-1000-DIR")]


def test_returned_direct_debit_with_its_fee_one_adjustment():
    bank = [B("b1", -49869, "DEVOLUCION RECIBO AM04 COMUNIDAD", "2026-07-14", "SDD1", "RC26-00280"),
            B("b2", -450, "COMISION DEVOLUCION RECIBO", "2026-07-14")]
    r = one(reconcile([acc(bank, id="CMA-1200", company="1200", gl="57200002")], ctx(receipt_customer={"RC26-00280": "C200041"})), "CMA-1200")
    assert cats(r) == {"b1": "RETURNED_DIRECT_DEBIT", "b2": "RETURNED_DIRECT_DEBIT"}
    assert lines(r["adjustments"][0]) == [("43000000", 49869, "C200041", "RC26-00280", None), ("57200002", -50319, None, None, None),
                                          ("62600000", 450, None, None, None)]


def test_pooling_sweep_not_booked_participant_and_header():
    part = acc([B("b1", -27053177, "TRASPASO CASH POOLING SALDO CERO", ref1="CP2607221200")], id="BIN-1200", company="1200")
    head = acc([B("b2", 500, "TRASPASO CASH POOLING BIN-1300", ref1="CP2607221300")], id="BIN-1000", company="1000")
    rows = reconcile([part, head], ctx())
    assert lines(one(rows, "BIN-1200")["adjustments"][0]) == [("55200000", 27053177, "1000", None, None), ("57200001", -27053177, None, None, None)]
    assert lines(one(rows, "BIN-1000")["adjustments"][0]) == [("55200000", -500, "1300", None, None), ("57200001", 500, None, None, None)]


def test_unrecorded_customer_receipt():
    r = one(reconcile([acc([B("b1", 51496121, "TRANSFERENCIA DE DIPUTACIÓN PROVINCIAL")])], ctx()))
    assert cats(r) == {"b1": "UNRECORDED_RECEIPT"}
    assert lines(r["adjustments"][0]) == [("55500000", -51496121, None, None, None), ("57200001", 51496121, None, None, None)]


def test_wrong_bank_account_cross_account():
    a = acc([B("b1", -431, "ORDEN NOMINAS 07/2026", "2026-07-31")])
    b = acc([], [K("e1#2", -431, "2026-07-31", reference="NOM202607")], id="CMA-1100", gl="57200002")
    rows = reconcile([a, b], ctx())
    assert cats(one(rows)) == {"b1": "WRONG_BANK_ACCOUNT"} and cats(one(rows, "CMA-1100")) == {"e1#2": "WRONG_BANK_ACCOUNT"}
    assert lines(one(rows)["adjustments"][0]) == [("57200001", -431, None, None, None), ("57200002", 431, None, None, None)]
    assert one(rows, "CMA-1100")["adjustments"] == []  # el ajuste va una sola vez


# ---------------------------------------------------------------- libro sin casar
def test_book_side_categories():
    dup_entry = [{"account": "40000000", "debit": 900, "credit": 0, "partner": "V4", "assignment": "K1"},
                 {"account": "57200001", "debit": 0, "credit": 900}]
    book = [K("c1#4", -900, reference="CF1", source="CONFIRMING"), K("c2#4", -900, reference="CF1", source="CONFIRMING", lines=dup_entry),
            K("p1#2", -378, "2026-07-02", reference="2026-037544", header="Pago domiciliado"),
            K("t1#1", 9000, "2026-07-31", reference="TRF07IT", source="TREASURY", header="Traspaso entre cuentas propias"),
            K("f1#1", 2503, "2026-07-01", reference="FXV-USD-2606", source="CLOSE_FX:reversal"),
            K("o1#2", -70, "2026-07-31", reference="URG07", source="MANUAL_PAYMENT")]
    prev = [B("j1", -378, "RECIBO ELÉCTRICA", "2026-06-30", ref2="2026-037544")]
    r = one(reconcile([acc([B("b1", -900, "CONFIRMING VTO", detail="CONFIRMING VTO REMESA CF1")], book, prev_bank=prev)], ctx()))
    assert r["matches"] == [{"bank_lines": ["b1"], "book_lines": ["c1#4"]}]
    assert cats(r) == {"c2#4": "BOOK_DUPLICATE", "p1#2": "PRIOR_PERIOD_BANK_ITEM", "t1#1": "TRANSFER_IN_TRANSIT",
                       "f1#1": "FX_REVALUATION", "o1#2": "OUTSTANDING_PAYMENT"}
    assert lines(adj(r, "BOOK_DUPLICATE")[0]) == [("40000000", -900, "V4", "K1", None), ("57200001", 900, None, None, None)]
    assert len(r["adjustments"]) == 1


# ---------------------------------------------------------------- dev: golden + invariantes
@pytest.fixture(scope="module")
def dev_rows(tmp_path_factory):
    from common import db
    from tasks import bank_rec
    conn = db.build_db(db.PHASES["dev"], tmp_path_factory.mktemp("d") / "dev.db")
    # simula a P1: ap_result con las decisiones del golden de AP
    gold_ap = [json.loads(l) for l in open(db.PHASES["dev"] / "golden/ap.jsonl")]
    conn.executemany("INSERT INTO ap_result(doc_id, company, vendor_id, invoice_number, decision) VALUES (?, ?, ?, ?, ?)",
                     [(r["doc_id"], r.get("company"), r.get("vendor_id"), r.get("invoice_number"), r["decision"]) for r in gold_ap])
    return conn, bank_rec.run(conn)


def test_dev_every_bank_and_book_line_explained_exactly_once(dev_rows):
    conn, rows = dev_rows
    assert len(rows) == 12
    for r in rows:
        bank = [b for m in r["matches"] for b in m["bank_lines"]] + [x["bank_line"] for x in r["unmatched_bank"]]
        expected = {x for (x,) in conn.execute("SELECT bank_line FROM bank_line WHERE account = ? AND month = '2026-07'", (r["account"],))}
        assert sorted(bank) == sorted(expected), r["account"]
        # cada línea de libro una vez (salvo BOOK_AMOUNT_ERROR: casada y además señalada como error de libro)
        book = [k for m in r["matches"] for k in m["book_lines"]] + [x["book_line"] for x in r["unmatched_book"] if x["category"] != "BOOK_AMOUNT_ERROR"]
        assert len(book) == len(set(book)), r["account"]
    assert conn.execute("SELECT COUNT(*) FROM bank_explained").fetchone()[0] == conn.execute(
        "SELECT COUNT(*) FROM bank_line WHERE month = '2026-07'").fetchone()[0]


def test_dev_score_against_golden(dev_rows):
    from common import db
    import score  # participant/score.py (common.je lo pone en sys.path)
    gold = [json.loads(l) for l in open(db.PHASES["dev"] / "golden/bank_rec.jsonl")]
    s, detail = score.score_bank(gold, dev_rows[1])
    assert s >= 0.999, detail


def test_dev_book_plus_adjustments_ties_to_statement_closing(dev_rows):
    """Fuente de verdad: 572 al cierre + ajustes − partidas de libro abiertas + cargos sin ajuste = saldo final del extracto."""
    from tasks.bank_rec import residuals
    conn, rows = dev_rows
    res = residuals(conn, rows)
    assert len(res) == 11 and all(v == 0 for v in res.values()), res  # la cuenta USD (libro en MXN) no entra
