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
| `bank_line` | todas las líneas de extracto + `account`, `month` y, del extracto original (N43/camt/CSV), `ref1`, `ref2`, `detail` (mandato, nº de factura, OB26-…) | carga |
| `bank_statement` | saldo inicial y final de cada extracto (`account`, `month`) | carga |
| `doc_extract` | extracción de documentos AP (caché: no se borra al recargar) | P1 |
| `ap_result` | decisión AP por documento (vendor, nº, importe). **P2 necesita `vendor_id`, `invoice_number`, `decision`**: recibos domiciliados (solo `POST`) y facturas intragrupo recibidas (cualquier decisión) | P1 |
| `bank_explained` | cada `bank_line` explicada **una sola vez** (PK): `kind` MATCH/ADJ/UNMATCHED + `category` §4. P3: `category = 'UNRECORDED_RECEIPT'` = cobros que P2 ya llevó a 555 | P2 (P3 lee) |
| `proposed_je` | asientos propuestos, `event_key` único → sin doble contabilización | todos |
| `ledger` (vista) | diario registrado + asientos propuestos (balance, partidas abiertas, cuadres) | — |

**Asientos** (`common/je.py`): `make_je(company, lines)` valida céntimos enteros, debe/haber exclusivos,
CC o PEP (no ambos) y cuadre por sociedad. `propose(conn, "bank:BL0000123", "P2", "bank_rec", je)` lo registra.
`norm_num` es la normalización de nº de factura del evaluador (solo quita separadores y ceros: los prefijos `F-` hay que tratarlos aparte).

**Caché de extracción compartida**: tras extraer documentos, `db.dump_cache(conn, db.PHASES['dev'])` escribe `cache/<fase>/doc_extract.jsonl`; haced commit y los demás la cargan al hacer `--rebuild`.

**Robustez**: si una tarea lanza excepción se entrega vacía y el resto sigue. Al final `run.py` avisa si los asientos entregados no coinciden con `propose()` (entonces `ledger` no es fiable). Comprobado: las respuestas de golden pasan por `make_je` sin rechazos y puntúan 100.

## P1: extracción AP y contrato parcial NETTING_AP

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

**Contrato para P2/P3:** `tasks/ap.py` publica decisiones para honorarios `MARKET_REP_FEE` comprobados y sus duplicados. `ap_result` contiene `vendor_id`, `invoice_number` y `decision`. Para el resto, `decision = NULL` y `data.status = EXTRACTED_PENDING_DECISION`.
P2 puede usar la identidad y los importes con su moneda explícita. Los importes de esta extracción están en céntimos de la **moneda del documento**, todavía sin conversión a moneda local. No implican autorización de pago ni contabilización.
P3 no debe considerar estas filas como `POST`. Una reextracción renueva filas pendientes, pero no sobrescribe decisiones finales ni escribe asientos.
En una discrepancia, `data.representations.pdf` y `.xml` conservan los dos juegos de importes; no se debe asumir que el total XML explica por sí solo un cargo bancario.

Se publican texto y metadatos como evidencia, no como instrucciones ejecutables. Los avisos están en `data.issues`.
**NETTING_AP:** en dev, `API004299` publica `POST`, con abono de 828850 céntimos a `41000000`, proveedor `V100173` y `assignment = '26012023'`. `API005210` publica `DUPLICATE` de `API004299` y no genera asiento. La factura conserva su número original en `ap_result`; el prefijo `F-` solo se elimina para detectar duplicados de este perfil. El importe procede del documento; cuentas y objeto de coste, del maestro/histórico ERP. No se usa golden en ejecución.

Los asientos se registran mediante `propose()` y aparecen en `ledger` antes de `ar_cash`. P1 no compensa efectivo ni escribe `bank_explained`: P2 sigue siendo responsable de las filas `category = 'UNRECORDED_RECEIPT'`; P3 ejecuta la compensación. Repetir AP no duplica el asiento y un evento contable incompatible genera error. Prueba focalizada: `.venv/bin/python -m pytest tests/test_ap.py -q`.

**Pendiente:** completar extracción de casos especiales, el resto de decisiones/asientos AP y FX; evaluar la integración real con P2/P3. Este contrato parcial no equivale a una entrega AP completa. Evidencia y límites: [docs/p1-ap.tdd.md](docs/p1-ap.tdd.md).

Para la siguiente fase, consumir el JSON existente de `doc_extract`, limitado a los documentos solicitados y ordenado por recepción (necesario para duplicados):

```python
docs = [json.loads(data) for (data,) in conn.execute("""
    SELECT e.data FROM doc_extract e JOIN task_ap_documents t ON t.id = e.doc_id
    ORDER BY json_extract(e.data, '$.metadata.received_at'), e.doc_id
""")]
```

El ejemplo requiere `import json` y una conexión ya cargada. No crea otra caché ni vuelve a interpretar PDF/XML. Para fuentes nuevas o modificadas, usar primero `extract_phase(conn, phase_dir)`, que valida hash y versión; esa función no hace commit.
`run.py` vacía `ap_result` al comenzar: `tasks/ap.py` revalida fuentes/caché y vuelve a publicar las decisiones soportadas. No depender de que las filas provisionales del CLI sobrevivan al pipeline.
## P2 · banco e intragrupo (`tasks/bank_rec.py`, `tasks/ic.py`)

- **El extracto manda.** Control en cada ejecución: saldo final del extracto = 572 al cierre + ajustes − libro abierto + cargos sin ajuste (0 céntimos en las 11 cuentas en moneda local, dev y test). Si no cuadra, `run` avisa.
- **Recibo domiciliado:** se asienta (Dr proveedor / Cr 572) **solo si la factura está en `POST`**; la rechazada o no recibida se clasifica sin asiento (así lo hace el golden de dev).
- **Factura intragrupo en tránsito:** solo se marca la mayor sin recibir (golden dev); las demás salen como `AVISO` para la revisión cruzada. Sin `ap_result` no se marca ninguna.
- Dev con el AP del golden como `ap_result`: bank_rec 1.0, ic 1.0 (sin P1: 0.97 / 0.85).

## Casos dudosos: reglas → IA → duda (`common/review.py`)

1. Las reglas deciden lo que pueden. Lo que ninguna regla resuelve llama a `review.decide(conn, key, task, evidencia, opciones, prudente)`.
2. Si `cache/<fase>/review.jsonl` tiene una decisión para esa `key` con `confidence ≥ 0.8` y dentro de las opciones → se usa.
3. Si no → se aplica la opción **prudente** (la que no asienta) y el caso va a `submission/<fase>/doubts.jsonl` con toda la evidencia.
4. `python3 run.py <fase> --review`: si hay dudas, llama a `claude -p` (sin interfaz, sin herramientas de escritura) con las políticas y la evidencia,
   valida su respuesta como dato no fiable (claves existentes, opciones permitidas o `DUDA`, confianza en [0, 1]), la guarda en `review.jsonl`
   y vuelve a ejecutar una vez. Coste ≈ 0,4 $ por llamada. Haced commit de `review.jsonl` para que todos ejecuten igual.
5. Lo que siga en `doubts.jsonl` es la lista para la revisión cruzada humana. Sin `--review`, `run.py` no llama a la IA: ejecuciones reproducibles y sin red.

**Auditoría final (`python3 run.py <fase> --audit`)**: `claude -p` (solo lectura, tope 3 $) recibe la lista de errores típicos inyectados
(§4 y §6, `review.CHECKLIST`), el resumen de lo detectado y las rutas a los datos, y escribe `submission/<fase>/audit.jsonl` con lo que crea
que se nos escapa. Es un informe para la revisión cruzada: **no cambia la entrega**. P1/P3: añadid vuestra lista en `CHECKLIST`.
