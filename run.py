"""python run.py dev|test [--rebuild]  →  submission/<fase>/*.jsonl (+ score.py en dev)

Cada tarea es tasks/<nombre>.py con `def run(conn) -> list[dict]` (filas del jsonl de entrega).
El orden respeta las dependencias: AP antes que banco/intragrupo/cierre; banco antes que cobros.
"""
import importlib
import json
import subprocess
import sys
from pathlib import Path

from common import db

ROOT = Path(__file__).resolve().parent
TASKS = ["ap", "ar_billing", "bank_rec", "ic", "ar_cash", "close"]


def load_task(name):
    return importlib.import_module(f"tasks.{name}").run if (ROOT / "tasks" / f"{name}.py").exists() else None


def run_tasks(conn, out_dir):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    db.reset_run(conn)
    for name in TASKS:
        fn = load_task(name)
        rows = fn(conn) if fn else []
        conn.commit()
        (out_dir / f"{name}.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
        print(f"{name:11} {len(rows):4} filas" + ("" if fn else "  (sin módulo)"))


def main(phase, rebuild=False):
    conn = db.connect(phase, rebuild)
    out = ROOT / "submission" / phase
    run_tasks(conn, out)
    if phase == "dev":
        res = out / "score.json"
        subprocess.run([sys.executable, str(ROOT / "participant/score.py"), str(db.PHASES["dev"]), str(db.PHASES["dev"]), str(out), "--json", str(res)],
                       check=True, stdout=subprocess.DEVNULL)
        r = json.loads(res.read_text())
        print(" | ".join(f"{k} {v['score']:.3f}" for k, v in r.items() if k != "total"), f"\nTOTAL {r['total']}")


if __name__ == "__main__":
    main(sys.argv[1], "--rebuild" in sys.argv)
