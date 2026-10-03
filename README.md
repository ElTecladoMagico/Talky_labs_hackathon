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

## P2 · banco e intragrupo (`tasks/bank_rec.py`, `tasks/ic.py`)

- **El extracto manda.** Control en cada ejecución: saldo final del extracto = 572 al cierre + ajustes − libro abierto + cargos sin ajuste (0 céntimos en las 11 cuentas en moneda local, dev y test). Si no cuadra, `run` avisa.
- **Recibo domiciliado:** se asienta (Dr proveedor / Cr 572) **solo si la factura está en `POST`**; la rechazada o no recibida se clasifica sin asiento (así lo hace el golden de dev).
- **Factura intragrupo en tránsito:** solo se marca la mayor sin recibir (golden dev); las demás salen como `AVISO` para la revisión cruzada. Sin `ap_result` no se marca ninguna.
- Dev con el AP del golden como `ap_result`: bank_rec 1.0, ic 1.0 (sin P1: 0.97 / 0.85).
