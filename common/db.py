"""Carga una fase (dev/test) en SQLite. Las tablas del ERP se rehacen; las compartidas (caché LLM incluida) se conservan."""
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PHASES = {"dev": ROOT / "participant/phase_dev", "test": ROOT / "participant/phase_test"}
CACHE = ROOT / "cache"  # versionado en git: la extracción de documentos se comparte entre el equipo

SHARED = """
CREATE TABLE IF NOT EXISTS doc_extract(doc_id TEXT PRIMARY KEY, source TEXT, confidence REAL, data TEXT);
CREATE TABLE IF NOT EXISTS ap_result(doc_id TEXT PRIMARY KEY, company TEXT, vendor_id TEXT, invoice_number TEXT, invoice_norm TEXT,
                                     invoice_date TEXT, payable INTEGER, currency TEXT, decision TEXT, data TEXT);
CREATE TABLE IF NOT EXISTS bank_explained(bank_line TEXT PRIMARY KEY, account TEXT, kind TEXT, category TEXT, owner TEXT, ref TEXT);
CREATE TABLE IF NOT EXISTS proposed_je(event_key TEXT PRIMARY KEY, owner TEXT, task TEXT, company TEXT, lines TEXT);
"""
RUN_TABLES = ("ap_result", "bank_explained", "proposed_je")  # doc_extract es caché: sobrevive a todo

LEDGER = """
CREATE VIEW ledger AS
SELECT line_id AS ref, company, account, debit, credit, partner, assignment, cost_center, wbs, 'recorded' AS origin FROM je_line
UNION ALL
SELECT p.event_key, COALESCE(json_extract(l.value, '$.company'), p.company), json_extract(l.value, '$.account'),
       json_extract(l.value, '$.debit'), json_extract(l.value, '$.credit'), json_extract(l.value, '$.partner'),
       json_extract(l.value, '$.assignment'), json_extract(l.value, '$.cost_center'), json_extract(l.value, '$.wbs'), p.owner
FROM proposed_je p, json_each(p.lines) l;
"""


def _cell(v):
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    return int(v) if isinstance(v, bool) else v


def _load(conn, table, rows):
    cols = list(dict.fromkeys(k for r in rows for k in r))
    conn.execute(f'DROP TABLE IF EXISTS "{table}"')
    conn.execute(f'CREATE TABLE "{table}" ({", ".join(f"[{c}]" for c in cols)})')
    conn.executemany(f'INSERT INTO "{table}" VALUES ({", ".join("?" * len(cols))})', [[_cell(r.get(c)) for c in cols] for r in rows])


def _read_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def build_db(phase_dir, db_path):
    phase_dir, db_path = Path(phase_dir), Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(SHARED + "DROP VIEW IF EXISTS ledger; DROP TABLE IF EXISTS json_files; CREATE TABLE json_files(name TEXT PRIMARY KEY, content TEXT);")

    for f in sorted((phase_dir / "erp").glob("*.jsonl")):
        _load(conn, f.stem, _read_jsonl(f))
    for f in sorted((phase_dir / "erp").glob("*.json")) + sorted((phase_dir / "tasks").glob("*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        prefix = "task_" if f.parent.name == "tasks" else ""
        if isinstance(data, list) and data and not isinstance(data[0], dict):
            _load(conn, prefix + f.stem, [{"id": x} for x in data])
        elif isinstance(data, list):
            _load(conn, prefix + f.stem, data)
        else:
            conn.execute("INSERT INTO json_files VALUES (?, ?)", (f"{f.parent.name}/{f.stem}", json.dumps(data, ensure_ascii=False)))

    conn.execute("INSERT INTO json_files VALUES ('phase/dir', ?)", (json.dumps(str(phase_dir)),))  # para leer inbox/ desde las tareas
    jes = _read_jsonl(phase_dir / "erp/journal_entries.jsonl")
    head = ("company", "doc_type", "posting_date", "document_date", "reference", "header_text", "source")
    blank = dict.fromkeys(("partner", "cost_center", "wbs", "assignment", "tax_code"))
    _load(conn, "je_line", [dict({"line_id": f"{e['id']}#{l['line']}", "entry_id": e["id"]}, **{k: e.get(k) for k in head}, **dict(blank, **l))
                            for e in jes for l in e["lines"]])

    _load(conn, "bank_line", [dict(r, account=f.parent.name, month=f.name[:7])
                              for f in sorted((phase_dir / "bank").glob("*/*.lines.jsonl")) for r in _read_jsonl(f)])
    conn.executescript(LEDGER + "CREATE INDEX ix_je_acc ON je_line(company, account); CREATE INDEX ix_bank ON bank_line(account, month);")
    cache = CACHE / phase_dir.name / "doc_extract.jsonl"
    if cache.exists():
        conn.executemany("INSERT OR REPLACE INTO doc_extract VALUES (:doc_id, :source, :confidence, :data)", _read_jsonl(cache))
    conn.commit()
    return conn


def dump_cache(conn, phase_dir):
    """Vuelca doc_extract a cache/<fase>/doc_extract.jsonl para hacer commit y compartirlo."""
    path = CACHE / Path(phase_dir).name / "doc_extract.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = conn.execute("SELECT doc_id, source, confidence, data FROM doc_extract ORDER BY doc_id").fetchall()
    path.write_text("".join(json.dumps(dict(zip(("doc_id", "source", "confidence", "data"), r)), ensure_ascii=False) + "\n" for r in rows),
                    encoding="utf-8")


def connect(phase, rebuild=False):
    path = ROOT / "db" / f"kalmora_{phase}.db"
    if rebuild or not path.exists():
        return build_db(PHASES[phase], path)
    return sqlite3.connect(path)


def get_json(conn, name):
    return json.loads(conn.execute("SELECT content FROM json_files WHERE name = ?", (name,)).fetchone()[0])


def phase_dir(conn):
    return Path(get_json(conn, "phase/dir"))


def reset_run(conn):
    for t in RUN_TABLES:
        conn.execute(f"DELETE FROM {t}")
    conn.commit()
