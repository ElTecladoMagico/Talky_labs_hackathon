import pytest

from common import db
from common.statements import parse

N43 = "\n".join([
    "119102360613901502592607012607312000000385289509783KALMORA CONSTRUCCION         ",
    "22    36062607012607010301710000000022294773881728351765556937182026-037539     ",
    "2301RECIBO ELÉCTRICA DEL LLANO COMERCIALI REF. MANDATO V100028-1100             ",
    "2302FRA 2026-037539                                                             ",
    "22    3606260731260731170401000000000030000483498059                            ",
    "2301COMISION MANTENIMIENTO CUENTA                                               ",
    "3391023606139015025900002000000002259470000000000000000000200000038303003978    ",
    "88999999999999999999000006                                                      ",
]) + "\n"

CAMT = """<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.08"><BkToCstmrStmt><Stmt>
<Bal><Tp><CdOrPrtry><Cd>OPBD</Cd></CdOrPrtry></Tp><Amt Ccy="EUR">100.00</Amt><CdtDbtInd>CRDT</CdtDbtInd></Bal>
<Bal><Tp><CdOrPrtry><Cd>CLBD</Cd></CdOrPrtry></Tp><Amt Ccy="EUR">50.00</Amt><CdtDbtInd>DBIT</CdtDbtInd></Bal>
<Ntry><NtryRef>BL9</NtryRef><Amt Ccy="EUR">150.00</Amt><CdtDbtInd>DBIT</CdtDbtInd>
<NtryDtls><TxDtls><Refs><EndToEndId>PAGO FRAS SN-016</EndToEndId></Refs><RltdPties><Cdtr><Nm>Empreitadas Vidal</Nm></Cdtr></RltdPties>
<RmtInf><Ustrd>TRANSFERENCIA A EMPREITADAS / PAGO FRAS SN-016558</Ustrd></RmtInf></TxDtls></NtryDtls></Ntry>
</Stmt></BkToCstmrStmt></Document>"""

CSV = """\
Cuenta,901845230082284402,Moneda,USD,Periodo,01/07/2026 al 31/07/2026,Saldo inicial,47107.00
Fecha,Concepto,Referencia,Clave de rastreo,Cargo,Abono,Saldo
10/07/2026,"TRANSF. EXTERIOR USD 14,500.00 LONE MESA",F2620614,202607105908089688,14500.00,0.00,32607.00
31/07/2026,ABONO,,,0.00,25.00,32632.00
"""


def test_parse_n43_balances_refs_and_detail(tmp_path):
    f = tmp_path / "2026-07.n43"
    f.write_text(N43, encoding="latin1")
    st = parse(f)
    assert st["opening"] == 38528950 and st["closing"] == 38303003  # D/H: 1 = deudor (negativo), 2 = acreedor
    assert [l["amount"] for l in st["lines"]] == [-222947, -3000]
    first = st["lines"][0]
    assert first["ref1"] == "176555693718" and first["ref2"] == "2026-037539"
    assert "MANDATO V100028-1100" in first["detail"] and "FRA 2026-037539" in first["detail"]
    assert st["lines"][1]["ref1"] == "" and st["lines"][1]["detail"] == "COMISION MANTENIMIENTO CUENTA"


def test_parse_camt_uses_entry_ref_as_bank_line(tmp_path):
    f = tmp_path / "2026-07.camt053.xml"
    f.write_text(CAMT)
    st = parse(f)
    assert (st["opening"], st["closing"]) == (10000, -5000)
    l = st["lines"][0]
    assert l["bank_line"] == "BL9" and l["amount"] == -15000 and l["ref2"] == "PAGO FRAS SN-016"
    assert "SN-016558" in l["detail"] and "Empreitadas Vidal" in l["detail"]


def test_parse_csv_mx(tmp_path):
    f = tmp_path / "2026-07.csv"
    f.write_text(CSV)
    st = parse(f)
    assert (st["opening"], st["closing"]) == (4710700, 3263200)
    assert [l["amount"] for l in st["lines"]] == [-1450000, 2500]
    assert st["lines"][0]["ref2"] == "F2620614" and st["lines"][0]["ref1"] == "202607105908089688"


def test_misaligned_statement_fails_loudly(tmp_path):
    """Si el extracto y lines.jsonl no casan línea a línea, no se adivina: se para."""
    from common.statements import enrich
    with pytest.raises(ValueError, match="BLX"):
        enrich([{"bank_line": "BLX", "amount": -1}], {"lines": [{"amount": -2, "ref1": "", "ref2": "", "detail": ""}]})


@pytest.fixture(scope="module")
def dev(tmp_path_factory):
    return db.build_db(db.PHASES["dev"], tmp_path_factory.mktemp("d") / "dev.db")


def test_dev_every_bank_line_enriched_from_its_statement(dev):
    assert dev.execute("SELECT COUNT(*) FROM bank_line WHERE detail IS NULL").fetchone()[0] == 0


def test_dev_statements_are_internally_consistent(dev):
    """El extracto es la fuente de verdad: saldo inicial + movimientos = saldo final, 12 cuentas x 4 meses."""
    rows = dev.execute("""SELECT s.account, s.month, s.opening + COALESCE(SUM(b.amount), 0) - s.closing
                          FROM bank_statement s LEFT JOIN bank_line b ON b.account = s.account AND b.month = s.month
                          GROUP BY s.account, s.month""").fetchall()
    assert len(rows) == 48
    assert [r for r in rows if r[2]] == []
