# Golden de test (septiembre 2026) — notas del generador, iteración 1

## Qué se ha hecho
1. Lectura completa de README, participant/README, POLITICAS, FORMATO y `score.py`; análisis del golden de dev → `golden_patterns_dev.md`.
2. `run.py dev --rebuild` (Python 3.12; el `python3` de anaconda 3.8 rompe el pipeline): **dev 96,47** (AP 0,950; close 0,806; resto 1,000; balance 0,990).
3. `run.py test --rebuild` como punto de partida; cada fichero se regenera con scripts propios del scratchpad
   (`gen_ap.py`, `gen_rest.py`, `gen_close.py`, `gen_summary.py`, con `apje.py`, `conv.py`, `accr.py`, `tb.py`) y correcciones partida a partida.
4. Validaciones:
   * Constructor de asientos AP en formato golden validado en dev: **242/242 asientos idénticos** al golden (`je_match = 1`) a partir de sus líneas y su cabecera.
   * Todos los asientos de los 6 ficheros pasan por `common.je.make_je` (cuadre, céntimos enteros, debe/haber exclusivos, CC xor PEP).
   * Cobertura del 100 % de los ids de tasks (297 doc_id, 25 billing items, 34 bank_lines, 12 cuentas).
   * `python3 score.py phase_test phase_test phase_test/golden` → **100,00**, sin errores de formato.
   * Balances recalculados con la misma fórmula que reproduce dev al céntimo.
   * Referencia: el pipeline actual (`submission/test`) contra este golden saca **95,83** (AP 0,925; cobros 0,974; cierre 0,86; balance 0,987; resto 1,0).

## Filas por fichero
ap 297 · ar_billing 25 · ar_cash 34 · bank_rec 12 · ic 4 · close 82 (ACCRUAL 58, PREPAID 9, FX_REVAL 8, BAD_DEBT 7) ·
trial_balance_recorded 251 · trial_balance_truth 257 · summary.json
(`tagged`: IC 2, AP 231, BANK 58, AR_BILL 25, AR_CASH 34, CLOSE 82).

AP: POST 228, POST_PAYMENT_BLOCK 3, HOLD 20 (QTY 10, PRICE 6, BANK 2, VENDOR 2), REJECT 17, DUPLICATE 14, NOT_INVOICE 15.

## Criterio en casos dudosos (AP)
| doc | pipeline | golden | motivo |
|---|---|---|---|
| API005236 | REJECT VAT | **DUPLICATE de API004202** | escaneo OCR de LEA-023528 (leído "IEA"), mismas fecha, base, cuota y total; IVA 21 % correcto |
| API005262 | REJECT ARITHMETIC | **REJECT CFDI_MISMATCH** | XML total 3.869.736,42 ≠ PDF 3.869.263,57 (mismo patrón que API005228 en dev); reemisión API004788 POST |
| API004780 | REJECT CERT_CUMULATIVE | **HOLD PRICE_VARIANCE** | factura la medición del mes (no el origen); pos. 10 a 25,99 vs pedido 24,83 (+4,7 %, 342 €) |
| API005012 | REJECT CERT_CUMULATIVE | **HOLD PRICE_VARIANCE** | pos. 10 a 358,43 vs 332,31 MXN (+7,9 %); "esta certificación" = valor de las SES |
| API005261 | POST en 1910 | **REJECT WRONG_ADDRESSEE (company 1100)** | agua de la obra 2512 de 1100 (serie FV-2026-233xx de 1100, neto 79.012 = periodificación de agosto ACCR-API004587) dirigida a la UTE; la UTE ya tiene su factura (API004710, recibo FV-2026-23355) |
| API004684 / API004576 / API004663 | HOLD QTY | **POST (PO_REF_TYPO)** | pedidos 4500019059→4500019509, 4500081270→4500018270, 4500091225→4500019225; todas las entradas existen y casan cantidad e importe |
| API004674 | HOLD QTY | **POST (PO_REF_STALE)** | pedido 2025 4500014364 → marco 2026 4500019331; partes 1000033499/500 casan cantidad e importe |
| API004601 | HOLD ACCOUNTING_EVIDENCE | **POST** | casetas agosto sin pedido: el otro pedido de 412.145 (4500018610, OB-1100-2414.05, SES 1000033433); 4500018186 ya lo usa API004570 |
| API005614 | HOLD ACCOUNTING_EVIDENCE | **POST abono** | rectifica 26008191 (API004675, pedido 4500019368/10 → 62930000 OB-1100-2522.01 S10), `credit_note_of` API004675 |
| API005184 | HOLD AMBIGUOUS | **POST** | factura IC 1200→1100 limpieza final Hotel Mirador = OB-1100-2522; histórico V-IC1200: 62900000 al PEP `.05` |
| API005608 | POST a OB-1100-2416.05 | POST a **62300000 OB-1100-2515.05** | rappel sobre G202621059 (API004612, pedido 4500022484/10) |
| API004870 | payee null | **payee FACTOR** | cesión API005190 con efectos 09/09/2026 ≤ fecha factura 30/09 (las de 31/08 y 07/09 quedan sin factor) |
| API004814/4880/4903/4969 | todas a OB-1100-2522.05 | 2511 / 2520 / 2522 / **CC-1100-ADM** | orden de numeración V100029 (ADM va tras la factura de 1000 F2631722); faltan 2515 y 2524 |
| MX con retención (API004787/4788/4793/4794/4795 + 5233, 5262, 5012) | retención 0 | retención y líquido del PDF | el CFDI no la recoge (patrón dev) |
| 12 facturas de agua/residuos | canon a 628/6293 | **63100000 SEX** | convención dev |
| API004471 (transitario) | todo a 62400000 SEX | flete 62400000, aranceles **21300000**, IVA importación **47200000 SIMP** | histórico idéntico de V100122 |
| API005192 (embargo) | vendor V-IC1910 | vendor **V100114**, company 1910 | deudor B56944491; su única factura (API004699) se recibió antes (14/09) → payee null |
| PPB API004661/4580/4702 | — | se mantienen | certificados nuevos emitidos 05/09 y 09/09, posteriores a la fecha de factura |

Formato (como dev): cabecera y líneas en moneda del documento, abonos en positivo, IVA agregado por código, retenciones por código, `cases`
inferidos (no puntúan), NOT_INVOICE con `company/invoice_date/action_data` leídos del documento. HOLD/REJECT/DUPLICATE sin `lines` (dev sí las trae; no puntúa).

## Otros ficheros
* **ar_billing**: igual que el pipeline (todas las certificaciones CONFORME → 0 SKIP; revisiones AL01/PJ01 de 8 meses fechadas 04/09; PJ01 excluye OT-2026-998 pendiente).
  Solo se cambia el formato (`face: null`, asiento con metadatos y orden golden). Sin `face.registry` (dato futuro).
* **ar_cash**: BL0000316 → **SU26-00081** parcial 813.120 (la transferencia lo cita) y BL0000317 → **SU26-00098** 1.355.200 (el pipeline los cruzaba).
  Parciales sin causa (BL0000222, 0477, 0546, 0671, 0687, 0688) y duplicados (BL0000809/0810 → OVERPAYMENT_DUPLICATE) como en dev.
  Las penalidades notificadas (SU26-00108 13.073,33; SU26-00114 4.725,26) no tienen cobro en el mes → sin residual.
* **bank_rec**: casación del pipeline (cuadra a 0 céntimos con los saldos del extracto) + categorías de match, importes, refs estilo dev.
  Novedades de test: comisión de aval → 66900000; intereses trimestrales de préstamo sindicado/project finance (LOAN_INTEREST_NOT_BOOKED en banco);
  BOOK_AMOUNT_ERROR en BLC-2100 (pago 90 cént. de más a V100189).
* **ic**: tránsito solo 1000→1200 (IC1000-26-0042), WRONG_TRADING_PARTNER 1000-1100 (CP2609291100), DUPLICATE_POSTING 1000-2100 (IC1000-26-0034 otra vez el 03/09),
  POOLING_NOT_BOOKED 1000-1200 (CP2609221200). Sin INTEREST_DAY_COUNT: septiembre tiene 30 días y ambas partes devengaron 2.500.000 €.
* **close**:
  * ACCRUAL estimado (no se conocen las facturas de octubre): mensuales = media de las 3 últimas; luz = 50 % del ciclo 16/09–15/10 por suministro; agua = 30/61 del bimestre sep-oct;
    exactos: V100029/1100 obras 2515 y 2524 ciclo 17/08–15/09 completo (2 × periodificación de agosto: API004852, API004916) y V100034/1100 jul-ago 79.012 (API004587, ver API005261).
    Backtest del estimador (media 3) contra el cierre real de agosto: 34/45 claves dentro del ±15 %.
  * PREPAID: fórmula exacta (API004488 −1.291.600; el pipeline daba −1.291.599).
  * FX_REVAL y BAD_DEBT: importes del pipeline (validados 1,000 en dev) verificados a mano en AP USD/EUR; añadidos `foreign`, `rate`, `previous`, `target`.

## Dudas abiertas
1. **IC tránsito**: por política deberían marcarse las 5 facturas IC del 30/09 no recibidas (1200, 1300, 2100, 3100, 1910). Dev solo marcó la que llegó tarde y agosto
   ninguna (todas llegaron antes del día 3); como test repite los pares de dev en las demás causas, se marca solo 1000-1200. Alternativa: añadir las otras 4.
2. **BOOK_AMOUNT_ERROR**: se deja como match (categoría BOOK_AMOUNT_ERROR) **y** en `unmatched_book`; dev no tiene precedente.
3. **API005261**: podría ser una segunda acometida legítima de la UTE (descartado por serie, importe y periodificación de agosto).
4. Periodificaciones: presencia de V100147 en 1100 (sin factura desde julio) y V100125 (consultoría irregular); fracción 0,5 vs 14/29 en luz.
5. `tagged.BANK` y `tagged.IC`: fórmula de dev no reproducible exactamente.
6. API004204-like: no se ha visto MULTI_PO en test. Proveedores no dados de alta (API005628/5629): sin periodificación.
