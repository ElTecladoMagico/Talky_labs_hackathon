"""Constructor único de asientos (formato FORMATO_ENTREGA) y registro de asientos propuestos."""
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "participant"))
from score import norm_num  # noqa: E402,F401  misma normalización de nº de factura que el evaluador


def make_je(company, lines):
    out, bal = [], defaultdict(int)
    for l in lines:
        d, c = l.get("debit") or 0, l.get("credit") or 0
        if not isinstance(d, int) or not isinstance(c, int) or d < 0 or c < 0 or (d and c):
            raise ValueError(f"línea inválida (céntimos enteros, solo debe o haber): {l}")
        if l.get("cost_center") and l.get("wbs"):
            raise ValueError(f"cost_center y wbs a la vez: {l}")
        line = dict(l, debit=d, credit=c)
        for k in ("partner", "cost_center", "wbs"):
            line.setdefault(k, None)
        out.append(line)
        bal[l.get("company") or company] += d - c
    descuadre = {k: v for k, v in bal.items() if v}
    if descuadre:
        raise ValueError(f"el asiento no cuadra por sociedad: {descuadre}")
    return {"company": company, "lines": out}


def propose(conn, event_key, owner, task, je):
    """Registra un asiento propuesto. event_key único: el mismo hecho no se contabiliza dos veces (IntegrityError)."""
    conn.execute("INSERT INTO proposed_je VALUES (?, ?, ?, ?, ?)", (event_key, owner, task, je["company"], json.dumps(je["lines"], ensure_ascii=False)))
