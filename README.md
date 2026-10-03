# Talky Labs Hackathon — Grupo Kalmora

Material de desarrollo para el desafío de cierre contable con IA de Grupo Kalmora.

El ejercicio incluye cuentas a pagar, facturación, aplicación de cobros, conciliación bancaria, conciliación intragrupo y ajustes de cierre. Los datos son sintéticos.

## Documentación

- [Descripción del desafío](participant/README.md)
- [Políticas contables](participant/POLITICAS_CONTABLES.md)
- [Formato de entrega](participant/FORMATO_ENTREGA.md)

La carpeta `participant/phase_dev/` contiene los datos de julio de 2026 y las respuestas de referencia en `golden/`. El archivo `kalmora_participant_dev.zip` conserva el paquete original.

## Evaluación local

Desde la carpeta `participant/`, con Python 3:

```bash
python3 score.py phase_dev phase_dev mi_entrega_dev/
```

## Pipeline del equipo

```bash
python3 run.py dev --rebuild   # carga SQLite (db/kalmora_dev.db), ejecuta tareas, puntúa con score.py
python3 run.py test            # misma ejecución sobre participant/phase_test → submission/test/
python3 -m pytest              # tests de la infraestructura
```

**Cada tarea** es `tasks/<nombre>.py` con `def run(conn) -> list[dict]` (filas del jsonl de entrega).
Orden de ejecución: `ap → ar_billing → bank_rec → ic → ar_cash → close`. Si el módulo no existe, se entrega vacío.

**SQLite** (`common/db.py`): cada `erp/*.jsonl` es una tabla con su nombre (campos anidados como JSON);
listas de `tasks/` → `task_<nombre>(id)`; JSON sueltos → `db.get_json(conn, "tasks/close")`.

| Tabla / vista | Qué es | Quién escribe |
|---|---|---|
| `je_line` | diario desplegado, `line_id` = `<asiento>#<línea>` | carga |
| `bank_line` | todas las líneas de extracto + `account`, `month` | carga |
| `doc_extract` | extracción de documentos AP (caché: no se borra al recargar) | P1 |
| `ap_result` | decisión AP por documento (vendor, nº, importe) | P1 |
| `bank_explained` | cada `bank_line` explicada **una sola vez** (PK) | P2 (P3 lee) |
| `proposed_je` | asientos propuestos, `event_key` único → sin doble contabilización | todos |
| `ledger` (vista) | diario registrado + asientos propuestos (balance, partidas abiertas, cuadres) | — |

**Asientos** (`common/je.py`): `make_je(company, lines)` valida céntimos enteros, debe/haber exclusivos,
CC o PEP (no ambos) y cuadre por sociedad. `propose(conn, "bank:BL0000123", "P2", "bank_rec", je)` lo registra.
`norm_num` es la normalización de nº de factura del evaluador (solo quita separadores y ceros: los prefijos `F-` hay que tratarlos aparte).

**Caché de extracción compartida**: tras extraer documentos, `db.dump_cache(conn, db.PHASES['dev'])` escribe `cache/<fase>/doc_extract.jsonl`; haced commit y los demás la cargan al hacer `--rebuild`.

**Robustez**: si una tarea lanza excepción se entrega vacía y el resto sigue. Al final `run.py` avisa si los asientos entregados no coinciden con `propose()` (entonces `ledger` no es fiable). Comprobado: las respuestas de golden pasan por `make_je` sin rechazos y puntúan 100.

## P1: extracción AP (primer hito, no entrega contable final)

La extracción está en `tasks/ap_extract.py`. Reutiliza XML estándar, pypdf y la infraestructura SQLite. Para los PDF escaneados usa OCR **local** de Vision en macOS, sin servicios externos.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-ap.txt
swiftc -module-cache-path /private/tmp/p1-swift-module-cache scripts/ocr_pdf.swift -o .venv/bin/ap-ocr
.venv/bin/python -m tasks.ap_extract dev --rebuild
.venv/bin/python -m tasks.ap_extract test --rebuild
.venv/bin/python -m pytest
```

El comando Swift es solo para macOS. Sin el binario, los escaneos quedan señalados como `OCR_REQUIRED`.
La caché compartible está en `cache/phase_dev/doc_extract.jsonl` y `cache/phase_test/doc_extract.jsonl`.
Solo se reutiliza cuando coinciden los bytes de fuentes/metadata y la versión del parser; hay que aumentar `VERSION` si cambia la interpretación del documento.

**Contrato provisional para P2/P3:** `ap_result.decision = NULL` y `data.status = EXTRACTED_PENDING_DECISION`.
P2 puede usar la identidad y los importes con su moneda explícita. Los importes de esta extracción están en céntimos de la **moneda del documento**, todavía sin conversión a moneda local. No implican autorización de pago ni contabilización.
P3 no debe considerar estas filas como `POST`. Una reextracción renueva filas pendientes, pero no sobrescribe decisiones finales ni escribe asientos.
En una discrepancia, `data.representations.pdf` y `.xml` conservan los dos juegos de importes; no se debe asumir que el total XML explica por sí solo un cargo bancario.

Se publican texto y metadatos como evidencia, no como instrucciones ejecutables. Los avisos están en `data.issues`.
**Pendiente:** completar extracción de casos especiales y construir `tasks/ap.py` con decisiones, asientos y evaluación dev. Evidencia y límites: [docs/p1-ap.tdd.md](docs/p1-ap.tdd.md).
