"""python run.py dev|test [--rebuild]  →  submission/<fase>/*.jsonl (+ score.py en dev)

Cada tarea es tasks/<nombre>.py con `def run(conn) -> list[dict]` (filas del jsonl de entrega).
El orden respeta las dependencias: AP antes que banco/intragrupo/cierre; banco antes que cobros.
"""
import importlib
import json
import subprocess
import sys
import traceback
from collections import defaultdict
from pathlib import Path

from common import db, review
from common.je import je_lines  # extracción de líneas del evaluador

ROOT = Path(__file__).resolve().parent
TASKS = ["ap", "ar_billing", "bank_rec", "ic", "ar_cash", "close"]


def load_task(name):
    return importlib.import_module(f"tasks.{name}").run if (ROOT / "tasks" / f"{name}.py").exists() else None


def _entries(name, row):
    """Asientos de una fila de entrega, igual que score_tb los suma al balance."""
    if name in ("ap", "ar_billing", "close"):
        return [row.get("journal_entry")]
    if name in ("ar_cash", "ic"):
        return [row.get("adjustment")]
    return [a.get("lines", []) for a in row.get("adjustments", [])] if name == "bank_rec" else []


def inconsistencies(conn, rows_by_task):
    """(sociedad, cuenta) donde lo entregado ≠ lo registrado con propose(). Vacío = la vista ledger es fiable."""
    diff = defaultdict(int)
    for name, rows in rows_by_task.items():
        for r in rows:
            for je in _entries(name, r):
                for c, acc, amt, *_ in je_lines(je, r.get("company")):
                    diff[(c, acc)] += amt
    for company, lines in conn.execute("SELECT company, lines FROM proposed_je"):
        for c, acc, amt, *_ in je_lines(json.loads(lines), company):
            diff[(c, acc)] -= amt
    return {k: v for k, v in diff.items() if v}


def run_tasks(conn, out_dir):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    db.reset_run(conn)
    done = {}
    for name in TASKS:
        fn, note = load_task(name), "  (sin módulo)"
        rows = []
        if fn:
            try:
                rows, note = fn(conn), ""
                conn.commit()
            except Exception:
                conn.rollback()
                traceback.print_exc()
                note = "  ¡FALLÓ! se entrega vacío"
        done[name] = rows
        (out_dir / f"{name}.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
        print(f"{name:11} {len(rows):4} filas{note}")
    bad = inconsistencies(conn, done)
    if bad:
        print(f"AVISO: asientos entregados ≠ propose() en {len(bad)} cuentas: {dict(list(bad.items())[:5])}")


def main(phase, rebuild=False):
    conn = db.connect(phase, rebuild)
    out = ROOT / "submission" / phase
    review.load(conn, db.CACHE / db.PHASES[phase].name / "review.jsonl")  # decisiones de la IA, versionadas
    run_tasks(conn, out)
    n = review.dump_doubts(conn, out / "doubts.jsonl")
    print(f"dudas: {n} → {out / 'doubts.jsonl'}" + ("  (pasar a la IA; sus decisiones van a cache/<fase>/review.jsonl)" if n else ""))
    if phase == "dev":
        res = out / "score.json"
        subprocess.run([sys.executable, str(ROOT / "participant/score.py"), str(db.PHASES["dev"]), str(db.PHASES["dev"]), str(out), "--json", str(res)],
                       check=True, stdout=subprocess.DEVNULL)
        r = json.loads(res.read_text())
        print(" | ".join(f"{k} {v['score']:.3f}" for k, v in r.items() if k != "total"), f"\nTOTAL {r['total']}")


if __name__ == "__main__":
    main(sys.argv[1], "--rebuild" in sys.argv)
