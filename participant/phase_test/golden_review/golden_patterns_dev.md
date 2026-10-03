# Patrones del golden de dev (julio 2026) — documento de referencia

Autor: agente generador, iteración 1. Fuente: `participant/phase_dev/golden/*` cruzado con `phase_dev/{tasks,inbox,bank,erp}`,
`POLITICAS_CONTABLES.md`, `FORMATO_ENTREGA.md` y `score.py`. Además se usa como **segunda verdad** el diario de `phase_test/erp`,
que contiene ya contabilizado el "truth" de julio y agosto (los asientos `CLOSE_*`, `IC_ACCRUAL`, `CASHAPP`… de 31/07 y 31/08):
es la mejor pista sobre cómo razona el generador en meses sin golden.

Todos los scripts de comprobación están en el scratchpad de la sesión (`apje.py`, `conv.py`, `tb.py`, `prep_chk.py`, `bt.py`…).

---------------------------------------------------------------------------------------------------------------------------

## 0. Qué puntúa `score.py` (y qué no)

| Fichero | Clave | Lo que puntúa | Lo que NO puntúa |
|---|---|---|---|
| ap | `doc_id` | F1 macro de `decision` (30 %); cabecera `company, vendor_id, invoice_number (norm_num), invoice_date, net, tax, gross, withholding, retention, payable` ±1 cént. (15 %); imputación por línea `(account, cost_center, wbs, tax_code)` ponderada por importe (15 %); `po/po_item` (10 %); asiento línea a línea ±2 cént. (20 %); motivos (5 %: intersección no vacía; en DUPLICATE, `duplicate_of` exacto); `payee.type` + `payment_block` (5 %) | `cases`, `due_date`, `credit_note_of`, `goods_receipts`, `action`, `action_data`, ids/fechas/textos del asiento. Cabecera, líneas y asiento **solo** para `POST`/`POST_PAYMENT_BLOCK` |
| ar_billing | `billing_item` | `expected`; si INVOICE: `tax_code, due_date, net, tax, retention, payable` y los 3 DIR3 de `face` (60 %) + asiento (40 %) | `date`, `gross`, `deductions`, `lines`, `face.registry`, metadatos del asiento |
| ar_cash | `bank_line` | `customer` 15 %, multiconjunto `(invoice|pagare, amount)` 45 %, multiconjunto `(type, amount)` de residuals 20 %, ajuste 20 % | `account/company/date/amount/kind`, `residuals[].invoice/account` |
| bank_rec | `account` | F1 de pares (bank_line, book_line) 45 %; F1 de partidas sin casar 20 %; acierto de categoría 15 %; ajustes 20 % (se juntan todas las líneas de todos los ajustes de la cuenta) | `matches[].category`, importes de unmatched, `ref`, `gl_account`, saldos |
| ic | `(pair ordenado, cause)` | detección F1 60 % + ajuste 40 % | `account`, `detail`, `amount`, `responsible`, `note` |
| close | `ACCRUAL→(type,company,vendor)` sumado; `PREPAID→invoice`; `FX_REVAL→item`; `BAD_DEBT→customer`; `WIP→billing_item`; resto→customer | importe: ±15 % ACCRUAL, ±1 € resto; 0,4 si está a ±50 %; `DOUBTFUL_RECLASS` cuenta 1 | asientos (solo cuentan para el balance) |
| balance | `(company, account)` | `1 − Σ|truth − (recorded + todos los asientos entregados)| / Σ|truth − recorded|` | — |

Comparación de asientos (`je_match`): por `(cuenta, socio, CC, PEP)` e importe ±2 cént.; el socio solo cuenta en cuentas que
empiezan por 40/41/43/44/49/55/24/16 y el objeto de coste solo en 6/7/2. **El orden de las líneas y los metadatos no importan**, pero
el número de líneas sí (`hit / max(len(g), len(s))`): partir o agregar líneas cambia la nota.

---------------------------------------------------------------------------------------------------------------------------

## 1. `summary.json` y balances

```json
{"phase":"dev","month":"2026-07","ap_documents":305,"ar_billing_items":26,"ar_receipts":32,"bank_accounts":12,
 "ic_differences":5,"close_entries":76,"tagged":{"IC":3,"AP":242,"BANK":54,"AR_BILL":25,"AR_CASH":32,"CLOSE":76}}
```

* Recuentos = nº de filas de cada fichero (`ic_differences` = filas de ic, `close_entries` = filas de close).
* `tagged` (no lo usa el scorer). Comprobado: `AP` = 242 = nº de asientos AP (POST) = 305 − 63 no contabilizados;
  `AR_BILL` = facturas emitidas (25); `AR_CASH` = cobros con ajuste (32); `CLOSE` = filas de close (76);
  `IC` = 3 = causas inyectadas que no son "naturales" (INTEREST_DAY_COUNT, WRONG_TRADING_PARTNER, DUPLICATE_POSTING; tránsito y pooling no cuentan).
  `BANK` = 54 no se reproduce exactamente (56 ajustes, 61+9 partidas sin casar…). **Duda abierta**; en test se usa nº de ajustes.
* `trial_balance_recorded.jsonl`: suma `debit − credit` por `(company, account)` de **todo** `erp/journal_entries.jsonl` (sin filtro de fecha),
  solo saldos ≠ 0, ordenado por sociedad y cuenta. Reproducido al céntimo (244 filas).
* `trial_balance_truth.jsonl`: recorded + todos los asientos del golden sumados exactamente como `score_tb` (ap/ar_billing `journal_entry`,
  ar_cash/ic `adjustment`, bank_rec `adjustments[].lines`, close `journal_entry`), saldos ≠ 0. Reproducido al céntimo (259 filas).
  ⇒ El golden es autoconsistente: la verdad del balance **es** recorded + golden.

---------------------------------------------------------------------------------------------------------------------------

## 2. AP (`ap.jsonl`, 305 filas)

### 2.1 Esquema
Factura/abono: `doc_id, document_type, decision, reasons, cases, company, vendor_id, invoice_number, invoice_date, currency, net, tax, gross,
withholding, retention, payable, due_date, duplicate_of, credit_note_of, payee, payment_block, lines[{amount, account, cost_center, wbs,
tax_code, po, po_item, goods_receipts[]}], journal_entry{id, company, doc_type (KR factura / KG abono), posting_date, document_date,
reference, header_text, source:"AP", currency, lines[{line, account, debit, credit, currency, amount_doc, partner, cost_center, wbs, tax_code,
assignment, text}]}` (journal_entry solo en POST/PPB).
NOT_INVOICE: `doc_id, document_type, decision, reasons:[], cases:[], company, vendor_id, invoice_number, invoice_date, currency, action, action_data`.

* **Moneda de cabecera y líneas = moneda del documento** (no la local): API004482 USD `net 240000`, asiento en EUR 193767 con
  `amount_doc` 240000. Igual API004559 (USD en 3100), API005164 (factura IC en EUR recibida por 3100), API004469 (anticipo USD).
* **Abonos en positivo**: `net/tax/gross/payable/lines.amount` positivos; el signo va en el asiento (Cr gasto, Dr proveedor).
* `due_date` = `invoice_date + vendor.payment_terms_days` (290/291).
* `invoice_number` canónico: en reenvíos con prefijo `F-` o números escritos distinto, el número del original.
* `credit_note_of` = doc_id de la factura rectificada (puede estar en el histórico, p.ej. API005587 → API004022).
* `id` del asiento: serie `<soc>-2026-51xxxxxxxx` (abonos `52…`) consecutiva tras la última del diario; `posting_date` = recepción + 0–5 días (ruido).

### 2.2 Decisiones y motivos (dev)
| decisión / motivo | nº | `cases` típicos |
|---|---|---|
| POST | 242 | PO_REF_MISSING 63, CORRECTED_REISSUE 15 (13 POST), CREDIT_NOTE 9, PRICE_SMALL 8, PO_REF_STALE 2, PO_REF_TYPO 1, MULTI_PO 1 |
| HOLD QTY_NOT_RECEIVED | 9 | QTY_NO_GR |
| HOLD PRICE_VARIANCE | 6 | PRICE_OVER |
| HOLD BANK_DETAILS_CHANGED | 2 | BANK_FRAUD (API005229 también CORRECTED_REISSUE) |
| HOLD VENDOR_NOT_IN_MASTER | 2 | NEW_VENDOR (`vendor_id` null) |
| REJECT WRONG_ADDRESSEE / ISP_NOT_APPLIED / VAT_RATE_INCORRECT | 3/3/3 | |
| REJECT MANDATORY_FIELD_MISSING / CERTIFICATION_CUMULATIVE_BILLED / WITHHOLDING_MISSING / ARITHMETIC_ERROR | 2/2/2/2 | |
| REJECT CFDI_MISMATCH | 1 | |
| DUPLICATE (`reasons:["DUPLICATE"]`) | 14 | DUPLICATE_NUMBER_VARIANT 5, DUPLICATE_RESEND 4, DUPLICATE_SCAN 3, DUPLICATE_PORTAL_AND_EMAIL 2 |
| NOT_INVOICE | 12 | CONTRACTOR_TAX_CERTIFICATE 4, PROFORMA 3, VENDOR_STATEMENT 3, FACTORING_NOTICE 1, BANK_DETAILS_CHANGE 1 |

Tipos: INVOICE 283, CREDIT_NOTE 9, DOWN_PAYMENT_REQUEST 1 (+ los 12 no-factura). No hubo POST_PAYMENT_BLOCK en dev.

Reglas deducidas:
* **Todo REJECT viene emparejado con una reemisión** (mismo proveedor y número) que se contabiliza (`CORRECTED_REISSUE`): API005226→API004206,
  API005214/API005229→API004180, API005216→API004188, API005218→API004201, API005223→API004242, API005225→API004466,
  API005228→API004323, API005211→API004128, API005215→API004220, API005219→API004478, API005220→API004480, API005212→API004219,
  API005222→API004213, API005213→API004222. La reemisión de un REJECT **no** es DUPLICATE (puede incluso repetir importe).
* **DUPLICATE**: mismo proveedor + número normalizado (sin guiones/barras/prefijo `F-`) de un documento ya **recibido** (histórico o antes en el mes)
  que se contabilizó o quedó en HOLD (API005198 duplica a un HOLD). El escaneo puede cambiar céntimos (API005205: 978998 vs 980824) y sigue siendo duplicado.
  `duplicate_of` = doc_id del primero.
* **Reenvío con IBAN distinto = fraude, no duplicado**: API005230 (mismo nº que API004112 POST, IBAN nuevo sin carta) → HOLD BANK_DETAILS_CHANGED.
* **CFDI_MISMATCH**: el XML del CFDI lleva un total ≠ PDF (API005228: XML 3254230 vs PDF 3169190). Gana sobre ARITHMETIC_ERROR.
* **ARITHMETIC_ERROR**: en la cabecera del golden `gross = net + tax` corregido (no el total declarado).
* **WRONG_ADDRESSEE**: el golden pone `company` = la sociedad correcta (la que tiene el contrato/pedido), no la destinataria del papel.
* **HOLD** lleva `lines` codificadas (con `goods_receipts`) aunque no puntúen.
* **Recuperación de pedido** (`PO_REF_STALE/TYPO/MISSING`): si el albarán/parte tiene entrada inequívoca bajo otro pedido del proveedor, se usa ese pedido y se contabiliza.
  MULTI_PO (API004204): factura con albaranes de dos pedidos → POST (el golden incluso referencia un GR que no está en el ERP).
* **Alquiler sin pedido citado** (API004095/API004123, casetas 412.145 €): se asignan a los dos pedidos de mismo precio con SES del mes (1 factura por pedido).
* **Suministros sin pedido** (luz/agua): objeto de coste del suministro. Para la luz (CUPS) el orden de numeración de las facturas del ciclo
  replica un orden estable de obras: V100028/1100 = 2512 < 2513 < 2617 < 2518 < 2521; V100029 (numeración compartida por sociedades)
  1100: 2511 < 2515 < 2520 < 2522 < 2524 < [1000] < ADM < [1300]. Si falta una factura del ciclo, se casa por importe histórico.

### 2.3 Asiento de factura (reconstruido al 100 %: 242/242 asientos con `je_match = 1` a partir de líneas y cabecera — `apje.py`)
* Línea con pedido y entrada: **Dr 40090000** por el valor de las entradas (Σ `goods_receipts[].amount`), socio proveedor, asignación `PO/pos`,
  texto "Compensación GR/IR PO/pos"; diferencia de precio dentro de tolerancia → Dr cuenta de gasto de la línea con su objeto. Una línea por entrada.
* Línea sin pedido: Dr gasto/inmovilizado con CC **o** PEP y `tax_code`; con pedido sin entrada (alquiler recurrente directo) → gasto con asignación `PO/pos`.
* **IVA agregado por código**: una sola línea 47200000 por código soportado (si hay un solo código = `tax` de cabecera); ISP/SIC/SIS/PAUT/PSIS: **un par**
  47210000 Dr / 47710000 Cr por código, cuota = round(Σ base × 21 % / 23 %). *El pipeline lo partía por línea → je 0,43.*
* Retención de garantía: Cr 40000900 socio proveedor, asignación nº factura (5 % de la base; obra ES/PT/MX).
* Retenciones IRPF/ISR/IVA ret.: **una línea 47510000 por código** (`MXISR10+MXIVAR` → dos líneas: 10 % y 10,67 % de la base), con socio proveedor y `tax_code` = código.
* Proveedor: Cr cuenta de conciliación de la ficha (40000000/41000000/40300000) por el líquido.
* Divisa: cada línea se convierte al cambio SYN-BCE de la fecha de factura (cruce vía EUR para USD→MXN) y redondeo por línea; el proveedor absorbe.
* **Canon / no sujetos**: "Canon de saneamiento autonómico (no sujeto a IVA)", "Canon autonómico sobre la deposición de residuos", "Suplidos: impuesto AJD" → **63100000** con SEX
  (no la cuenta de gasto del suministro). Primas de seguro e IPS → 62500000 SEX; rústicos → 62100000 SEX; agencia de viajes → 62910000 SREAV.
* Abono: inverso al mismo gasto/objeto **de la factura original** (si la original tenía pedido, se usa la cuenta/PEP de la posición), **sin** `po`.
* Anticipo (DOWN_PAYMENT_REQUEST): Dr 40700000 (sin socio en el golden) / Cr 40000000, al cambio de la fecha.
* Retención de garantía en México: el CFDI (XML) no la trae; el golden usa la del PDF ("Retención garantía 5 %" y "Total a pagar"). 5 docs en dev (API004311/312/313/317/319).
* Transitario (histórico V100122): flete 62400000 SEX, aranceles 21300000 (inmovilizado, CC-1100-MAQ) SEX, IVA de importación 47200000 SIMP.

### 2.4 Payee / bloqueo
* `payee` FACTOR si hay cesión vigente a la fecha de factura (ficha `alternative_payee.from_date` o notificación del mes con fecha de efectos ≤ fecha factura);
  AEAT_EMBARGO si la diligencia se recibió antes que la factura; si no, null.
* `POST_PAYMENT_BLOCK / CONTRACTOR_CERTIFICATE_EXPIRED`: subcontrata con ISP sin certificado art. 43 vigente a la fecha de factura
  (un certificado recibido después de la fecha de factura no la cubre).

### 2.5 Dónde falla el pipeline en dev (AP 0,950)
1. Asiento: IVA/ISP partidos por línea (≈30 docs je 0,43–0,45). 2. Retención de garantía de México no extraída (5). 3. Canon a 628/6293 en lugar de 631 (12).
4. Suministros eléctricos asignados a la obra equivocada cuando falta una factura del ciclo (3). 5. `HOLD ACCOUNTING_EVIDENCE_*` (motivo inexistente en la política) en 3 POST.
6. MULTI_PO → HOLD. 7. Fraude con mismo número tratado como duplicado (API005230). 8. Escaneo con céntimos distintos no detectado como duplicado (API005205).
9. CFDI_MISMATCH reportado como ARITHMETIC_ERROR. 10. Formato: cabecera en moneda local y abonos en negativo (si se convierte al formato golden: 0,968).

---------------------------------------------------------------------------------------------------------------------------

## 3. AR facturación (`ar_billing.jsonl`, 26 filas: 25 INVOICE, 1 SKIP_PENDING_APPROVAL)
* Esquema: `billing_item, type, company, customer, contract, expected, invoice{date, due_date, tax_code, net, tax, gross, retention, deductions[{code, amount, account}],
  payable, currency, face{oficina_contable, organo_gestor, unidad_tramitadora, registry?}|null, lines[{description, amount, account, cost_center, wbs}]}, journal_entry`.
  SKIP: solo las 6 claves de cabecera.
* Tipos: OBRA_CERTIFICATION 14 (fecha = fin de mes, neto = a origen − anterior, una línea por capítulo a `70510000` con PEP `<obra>.<cap>`; pendiente de
  aprobación → SKIP y WIP en cierre: BILL-CV-OB-2100-2503-202607), SERVICE_MONTHLY 8 (canon + extraordinarios **con** conformidad, 70500000 con CC del contrato),
  PRICE_REVISION 2 (fecha = aprobación del decreto + 3 días; una línea por mes desde efectos, 70520000), PPA 1 (día 3 hábil; MWh × % truncado a milésimas × precio,
  truncado), MARKET_SETTLEMENT 1 (día 6 hábil; una línea por planta + desvíos negativos al CC ADM; vencimiento = fecha).
* Impuestos: R21/R10/RISP/PR06/PRAUT/MR16 del contrato; retención de garantía 5 % (obra privada y PT) → Dr 43000900; México: 5 al millar (0,5 % de la base, Dr 63100000)
  y amortización del anticipo 30 % del total con IVA (Dr 43800000, socio cliente) hasta agotar.
* `face` solo clientes públicos ES (3 DIR3 del maestro; en obra el golden añade `registry` del FACe, dato que solo existe a futuro y no puntúa).
* Asiento (DR, source SD, serie `<soc>-2026-18…`): Dr 43000000 (socio, asignación nº factura) por el líquido, Dr 43000900, Dr 63100000, Dr 43800000,
  Cr ingresos (con `tax_code`), Cr 47700000 por la cuota. Numeración de facturas por serie del contrato en el orden de tasks.
* El pipeline acierta 26/26.

## 4. AR cobros (`ar_cash.jsonl`, 32 filas)
* Esquema: `bank_line, account, company, date, amount, customer, kind ("TRANSFER"), applications[{invoice|pagare, amount}], residuals[{type, invoice?, amount, account}], adjustment[]`
  (líneas con `company` y ordenadas por cuenta).
* Casos: 25 aplicaciones directas (por referencia, FACe/aviso de pago, o importe = factura abierta más antigua), 3 **parciales sin causa** (60 %/40 %: BL0000495, BL0000701, BL0000707 —
  se aplica el importe cobrado y el resto queda abierto), FACTORED_MISDIRECTED 2 (Cr 55300000 FACTOR-BAE), PENALTY 1 (Dr 70590000, BL0000161), NETTING_AP 1
  (Dr 41000000 V100173 asignación nº factura del representante, BL0000567), OVERPAYMENT_DUPLICATE 1 (segunda transferencia "PAGO <fra>" sin ref1, Cr 43800000),
  NON_CUSTOMER 2 (fianza 56500000; devolución IVA PT 47000000).
* Los cobros que el banco no importó (UNRECORDED_RECEIPT en banco) también se aplican aquí (P2 los lleva a 555 y P3 los aplica).

## 5. Conciliación bancaria (`bank_rec.jsonl`, 12 cuentas)
* Esquema: `account, company, gl_account, currency, statement_opening, statement_closing, matches[{bank_lines, book_lines, category}], unmatched_bank[{bank_line, category, amount}],
  unmatched_book[{book_line, category, amount}], adjustments[{ref, category, lines[...]}]`. Matches ordenados por bank_line; líneas de ajuste ordenadas por cuenta.
* `matches.category`: MATCH 216, FX_RATE_DIFFERENCE 5, FACTORING_CHARGES_NOT_BOOKED 2, LOAN_INTEREST_NOT_BOOKED 1 (casación con diferencia que se ajusta).
* Sin casar (banco): BANK_FEE_NOT_BOOKED 31, DIRECT_DEBIT_NOT_BOOKED 17, INTEREST_NOT_BOOKED 4, RETURNED_DIRECT_DEBIT 4, CARD 1, BANK_ERROR 1, UNRECORDED_RECEIPT 1,
  WRONG_BANK_ACCOUNT 1, POOLING_NOT_BOOKED 1. (Libro): PRIOR_PERIOD_BANK_ITEM 4, OUTSTANDING_PAYMENT 1, TRANSFER_IN_TRANSIT 1, BOOK_DUPLICATE 1, WRONG_BANK_ACCOUNT 1, FX_REVALUATION 1.
* Ajustes (56): comisiones agrupadas por fecha+concepto+importe (`FEE-<cta>-<fecha>-<texto[:10]><importe>`, Dr 62600000; aval → 66900000); recibo domiciliado
  (`DD-<doc_id>`, Dr cuenta del proveedor, asignación nº factura) **solo si la factura está POST** (17 cargos → 14 ajustes); intereses (`INT-…`: Dr 572 neto, Dr 47300000 19 %,
  Cr 76200000); préstamo (Dr 66200000); tarjeta (62910000 CC-1000-DIR); devolución de recibo (Dr 43000000 cliente asignación RC, + comisión 62600000, un ajuste por par);
  pooling no registrado (55200000 socio 1000); cobro no importado (Cr 55500000); cuenta equivocada (reclasificación entre 572); duplicado de libro (anula el asiento);
  factoring (Dr 66500000 / Cr 55300000 FACTOR-BAE, interés + comisión del maestro de cesiones); FX de transferencias SWIFT (66800000/76800000).
* El extracto manda: saldo final = 572 + ajustes − libro abierto + cargos sin ajuste (0 céntimos en todas las cuentas EUR).

## 6. Intragrupo (`ic.jsonl`, 5 filas)
Esquema `pair, account, cause, detail, amount, responsible, adjustment[], note?`. Dev: INTEREST_DAY_COUNT 1000-3100 (3100 devengó 30/360: ajuste 66210000/55200000 en MXN,
amount en EUR 83333), INVOICE_IN_TRANSIT 1000-1200 (solo la factura que llegó tarde —17/08—; las recibidas el 3–4/08 no se marcan; ajuste del receptor Dr gasto
62940000 CC ADM / Cr 40090000 socio "1000" por la **base**), WRONG_TRADING_PARTNER 1000-1100 (barrido con socio 1200: reclasificar 55200000), DUPLICATE_POSTING 1000-2100
(anula el segundo asiento completo, con su autoliquidación PSIS), POOLING_NOT_BOOKED 1000-1200 (adjustment [] + note; el ajuste va en bank_rec).

## 7. Cierre (`close.jsonl`, 76 filas)
* ACCRUAL 57 (47 claves sociedad-proveedor): `type, company, vendor, invoice (doc_id de la factura FUTURA), amount, je, period[ini,fin], estimate:true, journal_entry`.
  **El generador usa la factura real que llega después del cierre** y prorratea por días: importe = neto × días del periodo dentro del mes / días del periodo
  (redondeo por línea, banker's). Ej.: agua bimestral jul-ago → 31/62 = 50 % en julio y 100 % en agosto si no ha llegado; luz ciclo 17/07–15/08 → 15/30 en julio;
  ciclo anterior no recibido → 100 %; mensuales (combustible, viajes, mensajería, material de oficina, telecom, consultores, residuos, energía PT/MX) → 100 % del mes.
  Una factura rechazada cuya reemisión llega el mes siguiente se periodifica completa (API004289; API004397 por WRONG_ADDRESSEE). Proveedores del conjunto:
  V100026/27 combustible, V100028/29 luz, V100030 telecom, V100033…V100046 y V100159 agua, V100125 consultoría, V100145 viajes, V100146 mensajería, V100147 oficina,
  V100157/163 residuos, V100195 (2100), V100209 (3100). **No** se periodifican profesionales esporádicos (V100129, V100210: falsos positivos del pipeline).
  Asiento: Dr gasto(s) con objeto (mismas líneas que la factura, 631 para el canon) / Cr 40090000 socio proveedor, asignación `ACCR-<doc>`.
* PREPAID 9: `amount` = variación de 48000000. Amortización exacta: `diferido_k = floor(T·(n−k)/n)`, cuota_k = diferido_{k−1} − diferido_k (T = gasto contabilizado);
  verificado en todo el histórico de `CLOSE_PREPAID` sin una sola discrepancia.
* FX_REVAL 8: `item, currency, foreign, rate (6 dec.), amount` = valor a cierre − valor contable (en positivo si la partida —activo o pasivo— aumenta); AP en divisa abiertas
  (SaaS USD de 1000, alquiler USD de 3100, factura IC en EUR de 3100), préstamo 16330000 y sus intereses 55200000 en 3100, cuenta USD. Los anticipos (DPR) pagados no se valoran.
* WIP_REVENUE 1: certificación no aprobada (Dr 43090000 cliente / Cr 71300000 PEP `.01`).
* BAD_DEBT 1: `customer, target, previous, amount` = provisión necesaria − anterior; base solo 43000000 vencido (privados y comunidades), >180 d 50 %, >365 d 100 %; concurso 100 % de todo.
* Pipeline dev: close 0,806 — las periodificaciones son la parte débil (método de estimación y doble conteo de ciclos de luz/agua).
