"""Casos que las reglas no resuelven. La IA decide FUERA del pipeline (sesión de Claude Code sobre doubts.jsonl) y sus
decisiones se versionan en cache/<fase>/review.jsonl, como la extracción: cada ejecución es reproducible y sin red.
Sin decisión válida y segura, se aplica la opción prudente y el caso queda marcado como duda."""
import json
from pathlib import Path

MIN_CONFIDENCE = 0.8


def load(conn, path):
    conn.execute("DELETE FROM review")
    if Path(path).exists():
        rows = [json.loads(l) for l in Path(path).read_text(encoding="utf-8").splitlines() if l.strip()]
        conn.executemany("INSERT OR REPLACE INTO review VALUES (?, ?, ?, ?)",
                         [(r["key"], r["decision"], float(r.get("confidence") or 0), r.get("reason")) for r in rows])


def decide(conn, key, task, evidence, options, fallback):
    row = conn.execute("SELECT decision, confidence FROM review WHERE key = ?", (key,)).fetchone()
    if row and row[0] in options and row[1] >= MIN_CONFIDENCE:
        return row[0]
    conn.execute("INSERT OR REPLACE INTO doubt VALUES (?, ?, ?, ?, ?)",
                 (key, task, json.dumps(evidence, ensure_ascii=False, default=str), json.dumps(options), fallback))
    return fallback


def dump_doubts(conn, path):
    rows = conn.execute("SELECT key, task, evidence, options, fallback FROM doubt ORDER BY task, key").fetchall()
    Path(path).write_text("".join(json.dumps({"key": k, "task": t, "evidence": json.loads(e), "options": json.loads(o), "fallback": f},
                                             ensure_ascii=False) + "\n" for k, t, e, o, f in rows), encoding="utf-8")
    return len(rows)
