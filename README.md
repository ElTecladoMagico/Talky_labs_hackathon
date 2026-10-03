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

## P1: extracción, decisiones AP y contrato para P2/P3

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

**Contrato para P2/P3:** `tasks.ap.run(conn)` publica una fila por documento solicitado en `ap_result`, con `vendor_id`, `invoice_number`, `payable`, `currency` y `decision` informada. Puede ser `POST`, `POST_PAYMENT_BLOCK`, `HOLD`, `REJECT`, `DUPLICATE` o `NOT_INVOICE`. Los asientos solo existen para las dos decisiones de contabilización; `HOLD` nunca equivale a autorización de pago. P3 puede usar cualquier decisión para comprobar que una factura IC ha llegado.
Los importes de la decisión están en céntimos de la moneda local, con conversión por fecha de factura y redondeo por línea. `source_currency`, `source_amounts`, `source_invoice_number` y `source_company` conservan los datos extraídos. Una ausencia de cambio para contabilizar produce `HOLD/FX_RATE_MISSING`.
**Consumir `ap_result`, no `doc_extract`, para decisiones y números canónicos.** La caché `doc_extract` conserva el texto y los importes originales, incluidos los prefijos `F-` de reenvíos. El CLI de extracción solo renueva filas pendientes; no decide ni crea asientos. `data.representations.pdf` y `.xml` mantienen las representaciones por separado.

Se publican texto y metadatos como evidencia, no como instrucciones ejecutables. Los avisos están en `data.issues`.
**NETTING_AP:** en dev, `API004299` publica `POST`, con abono de 828850 céntimos a `41000000`, proveedor `V100173` y `assignment = '26012023'`. `API005210` publica `DUPLICATE` de `API004299` y no genera asiento. Los cuatro reenvíos `API005197/5200/5206/5210` publican los números canónicos `0009557/F2611803/26030808/26012023`; se conserva la F propia de la serie. `API005221` queda `REJECT/ARITHMETIC_ERROR`, con `gross = payable = 264496` y total declarado `308802` en `source_amounts`, sin asiento.

**Correcciones de validación:** las facturas de energía `F2631650`, `F2631651` y `F2631668` contabilizan con los mismos asientos que golden. La imputación se infiere únicamente si hay un ciclo mensual completo y dos ciclos históricos completos con idéntico orden de objetos de coste; se registra `cost_evidence`. Si cambia la secuencia o falta información, se conserva la revisión. Esta inferencia deberá sustituirse por un maestro CUPS–objeto de coste cuando esté disponible.
El N43 aporta referencia de factura y mandato que no aparecen en `.lines.jsonl`. P1 contrasta factura, proveedor, moneda, importe y sociedad del mandato con el maestro de la cuenta bancaria. Así, `API005227` queda `REJECT/WRONG_ADDRESSEE`, `company=1100`, `source_company=1910`, sin asiento; `bank_evidence` identifica CMA-1100. Leer el extracto no modifica `bank_explained`.

Los asientos se registran mediante `propose()` y aparecen en `ledger` antes de `ar_cash`. P1 no compensa efectivo ni escribe `bank_explained`: P2 sigue siendo responsable de las filas `category = 'UNRECORDED_RECEIPT'`; P3 ejecuta la compensación. Repetir AP no duplica el asiento y un evento contable incompatible genera error. Prueba focalizada: `.venv/bin/python -m pytest tests/test_ap.py -q`.

**Validación:** 305 decisiones dev y 297 test en ejecución aislada, sin diferencias entre entrega y asientos propuestos. Score AP dev **0,939480**, F1 HOLD **0,818**; no es un resultado perfecto. Golden se usa como referencia de pruebas/evaluación, nunca como entrada de ejecución. Quedan discrepancias y la integración real con P2/P3. Evidencia y límites: [docs/p1-ap.tdd.md](docs/p1-ap.tdd.md).

Para consumir las decisiones después de ejecutar AP:

```python
docs = [json.loads(data) for (data,) in conn.execute("""
    SELECT e.data FROM ap_result e JOIN task_ap_documents t ON t.id = e.doc_id
    ORDER BY json_extract(e.data, '$.metadata.received_at'), e.doc_id
""")]
```

El ejemplo requiere `import json` y una conexión ya cargada. `tasks.ap.run(conn)` revalida el hash y la versión de las fuentes; el llamante hace commit o rollback.
`run.py` reinicia todas las tablas de resultados al comenzar y regenera `submission/<fase>/ap.jsonl`. Ejecutarlo como pipeline completo del equipo, no para refrescar solo P1 sobre resultados P2/P3 que se quieran conservar. Los archivos SQLite y `submission/` son locales e ignorados por Git: compartir solo la caché de extracción no publica decisiones.
