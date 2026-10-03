# Formato de entrega

Se entrega una carpeta por fase con estos ficheros JSON Lines (una línea por objeto). Todos son opcionales: lo que falte puntúa 0 en su tarea.

```
entrega/
├── ap.jsonl          ← uno por doc_id de tasks/ap_documents.json
├── ar_billing.jsonl  ← uno por billing_item de tasks/ar_billing_items.json
├── ar_cash.jsonl     ← uno por bank_line de tasks/ar_receipts.json
├── bank_rec.jsonl    ← uno por cuenta de tasks/bank_accounts.json
├── ic.jsonl          ← una línea por diferencia intragrupo encontrada
└── close.jsonl       ← una línea por partida de cierre
```

Reglas comunes:

- **Importes:** en **céntimos enteros** y en la moneda local de la sociedad.
- **Fechas:** `YYYY-MM-DD`.
- **Asientos:** el campo `journal_entry`, o `adjustment` / `lines` en los ajustes, lleva esta forma:

```json
{"company": "1100", "lines": [
  {"account": "40090000", "debit": 1234500, "credit": 0, "partner": "V100123", "cost_center": null, "wbs": null},
  {"account": "60000000", "debit": 1500, "credit": 0, "partner": null, "cost_center": null, "wbs": "OB-1100-2514.02"},
  {"account": "47200000", "debit": 259560, "credit": 0},
  {"account": "40000000", "debit": 0, "credit": 1495560, "partner": "V100123"}]}
```

Las líneas se comparan por cuenta, socio, objeto de coste e importe, con ±2 céntimos. El socio solo cuenta en las cuentas de partidas abiertas; el objeto de coste, en gastos, ingresos e inmovilizado. **Todos** vuestros asientos se suman al diario registrado para calcular el balance.

## ap.jsonl

```json
{"doc_id": "API005263", "document_type": "INVOICE", "decision": "POST", "reasons": [],
 "company": "1100", "vendor_id": "V100045", "invoice_number": "2026-032361", "invoice_date": "2026-08-31", "currency": "EUR",
 "net": 4202872, "tax": 0, "gross": 4202872, "withholding": 0, "retention": 210144, "payable": 3992728,
 "duplicate_of": null, "payee": null, "payment_block": null, "action": null,
 "lines": [{"amount": 1122330, "account": "60700000", "cost_center": null, "wbs": "OB-1100-2514.04", "tax_code": "SISP", "po": "4500019036", "po_item": 10}],
 "journal_entry": {"company": "1100", "lines": [...]}}
```

- `document_type`: `INVOICE | CREDIT_NOTE | DOWN_PAYMENT_REQUEST | PROFORMA | VENDOR_STATEMENT | FACTORING_NOTICE | TAX_GARNISHMENT_ORDER | BANK_DETAILS_CHANGE | CONTRACTOR_TAX_CERTIFICATE`
- `decision`: `POST | POST_PAYMENT_BLOCK | HOLD | REJECT | DUPLICATE | NOT_INVOICE`
- `reasons`: los códigos de la §2.2 de las políticas (por ejemplo `["PRICE_VARIANCE"]`).
- `payee`: `null` o `{"type": "FACTOR" | "AEAT_EMBARGO"}`.
- `payment_block`: `null` o `"CONTRACTOR_CERTIFICATE_EXPIRED"`.
- `action` (solo en `NOT_INVOICE`): `NONE | REGISTER_ALTERNATIVE_PAYEE | REGISTER_EMBARGO | UPDATE_BANK_DETAILS | UPDATE_CONTRACTOR_CERTIFICATE`.
- `vendor_id` es `null` si el proveedor no existe en el maestro.
- `journal_entry` solo con `POST` y `POST_PAYMENT_BLOCK`.

## ar_billing.jsonl

```json
{"billing_item": "BILL-CV-OB-1100-2521-202609", "expected": "INVOICE",
 "invoice": {"date": "2026-09-30", "due_date": "2026-10-30", "tax_code": "R21", "net": 65189436, "tax": 13689782, "retention": 0,
             "deductions": [], "payable": 78879218, "face": {"oficina_contable": "L0…", "organo_gestor": "L0…", "unidad_tramitadora": "L0…"},
             "lines": [{"description": "Capítulo 01 – …", "amount": 16031944, "account": "70510000", "wbs": "OB-1100-2521.01"}]},
 "journal_entry": {"company": "1100", "lines": [...]}}
```

- `expected`: `INVOICE | SKIP_PENDING_APPROVAL`.
- `face` solo para clientes públicos españoles.

## ar_cash.jsonl

```json
{"bank_line": "BL0005123", "customer": "C200014",
 "applications": [{"invoice": "SU26-00412", "amount": 45320000}],
 "residuals": [{"type": "PENALTY", "invoice": "SU26-00412", "amount": 90640}],
 "adjustment": [{"company": "1200", "account": "55500000", "debit": 45229360, "credit": 0},
                {"company": "1200", "account": "70590000", "debit": 90640, "credit": 0},
                {"company": "1200", "account": "43000000", "debit": 0, "credit": 45320000, "partner": "C200014"}]}
```

- `residuals[].type`: `PENALTY | NETTING_AP | OVERPAYMENT_DUPLICATE | FACTORED_MISDIRECTED | NON_CUSTOMER`.
- `customer` es `null` si el cobro no viene de un cliente.
- Un cobro de pagaré a su vencimiento se aplica así: `{"pagare": "<número>", "amount": …}`.

## bank_rec.jsonl

```json
{"account": "BIN-1100", "company": "1100",
 "matches": [{"bank_lines": ["BL0004410"], "book_lines": ["1100-2026-16000123#3", "1100-2026-16000124#2"]}],
 "unmatched_bank": [{"bank_line": "BL0004502", "category": "BANK_FEE_NOT_BOOKED"}],
 "unmatched_book": [{"book_line": "1100-2026-16000190#2", "category": "OUTSTANDING_PAYMENT"}],
 "adjustments": [{"category": "BANK_FEE_NOT_BOOKED", "lines": [{"company": "1100", "account": "62600000", "debit": 3000, "credit": 0},
                                                                {"company": "1100", "account": "57200001", "debit": 0, "credit": 3000}]}]}
```

- `book_line` = `<id del asiento>#<número de línea>` de `erp/journal_entries.jsonl`.
- Las categorías están en la §4 de las políticas.
- El identificador de cada línea del extracto está en `bank/<cuenta>/<mes>.lines.jsonl`.

## ic.jsonl

```json
{"pair": ["1000", "3100"], "cause": "INTEREST_DAY_COUNT", "amount": 1666700, "responsible": "3100",
 "adjustment": [{"company": "3100", "account": "66210000", "debit": 32051, "credit": 0},
                {"company": "3100", "account": "55200000", "debit": 0, "credit": 32051, "partner": "1000"}]}
```

## close.jsonl

```json
{"type": "ACCRUAL", "company": "1100", "vendor": "V100012", "amount": 182340, "journal_entry": {"company": "1100", "lines": [...]}}
{"type": "PREPAID", "company": "1000", "invoice": "API003311", "amount": -700000, "journal_entry": {...}}
{"type": "FX_REVAL", "company": "3100", "item": "GL:16330000", "amount": 1520000, "journal_entry": {...}}
{"type": "BAD_DEBT", "company": "1100", "customer": "C200007", "amount": 2500000, "journal_entry": {...}}
{"type": "WIP_REVENUE", "company": "1100", "billing_item": "BILL-…", "amount": 65189436, "journal_entry": {...}}
```

- `item` en `FX_REVAL` es `AP:<doc_id>` (factura de proveedor), `GL:16330000` o `GL:55200000` (préstamo intragrupo de 3100) o `BANK:BANH-3100-USD`.
- Los asientos de cierre se fechan el último día del mes; sus retrocesiones del día 1 **no** se entregan.
