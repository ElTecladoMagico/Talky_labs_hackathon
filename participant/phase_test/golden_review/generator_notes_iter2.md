# Golden de test — notas del generador, iteración 2

Punto de partida: `eval_iter1.md` (8,9/10). He revisado cada hallazgo contra los datos, incluida la verdad de julio y agosto que contiene el ERP de test (`ap_document_log`, `CLOSE_*` de 31/07 y 31/08).

## Hallazgos del evaluador

| ID | Decisión | Cambio realizado y justificación |
|---|---|---|
| **E1 · API004877** | **Aceptado** | Comprobado:<br>• la factura TKD26/28754 dice «Levantamiento topográfico y replanteo», que es el pedido **4500022726/10** (OB-1100-2419.05, 318.751, SES **1000033672** del 15/09, que nadie usaba);<br>• el pedido citado, 4500022762, es el de «Ensayos de compactación» de API004879;<br>• tal como estaba, la SES 1000033674 se consumía dos veces y la GR/IR de 4500022762/10 se cargaba por 625.508 frente a una partida abierta de −312.754.<br>Ahora: línea 318.751 / 62300000 / OB-1100-2419.05 / S21 / pedido 4500022726-10 / GR 1000033672. Asiento: Dr 40090000 318.751, Dr 47200000 66.938, Cr 41000000 385.689, sin línea de diferencia de precio. Caso PO_REF_TYPO. |
| **E2 · API005260** | **Aceptado** | `company` = 1200. Es la convención de dev para WRONG_ADDRESSEE (API005225) y la reemisión API004762 va a 1200. |
| **E3 · BAD_DEBT, redondeo** | **Aceptado y generalizado** | El organizador trunca el 50 % (49000000 de C200032: 39.639 sobre 79.279; C200050: 25.499 sobre 50.999). Ahora el deterioro se calcula de forma propia, partida a partida con `//2`, a partir de las partidas abiertas más las aplicaciones de ar_cash. Cambian tres importes:<br>• C200080: 35.497.752 → **35.497.751**<br>• C200038: 14.066 → **14.065**<br>• C200058: 10.230 → **10.229**<br>El resto coincide. |
| **E4 · FX BANK:BANH-3100-USD** | **Aceptado** | Importe = 10.346.300 × 16,764161 − (saldo 57200006 + ajustes de comisiones del golden de bank_rec) = **−9.112.159** (antes −9.112.164). |
| **E5 · `lines` en no contabilizadas** | **Aceptado (parcial)** | Ahora llevan líneas codificadas:<br>• DUPLICATE: copia de las líneas del original si este está en el mes;<br>• REJECT con reemisión: líneas de la reemisión con los importes del documento rechazado;<br>• HOLD y otros REJECT: posición de pedido por descripción y GR por albarán.<br>Quedan sin líneas 8 DUPLICATE de originales del histórico, 2 HOLD de proveedores no dados de alta, 2 HOLD de fraude de IBAN y 2 REJECT. No puntúa. |
| **D1 · ACCRUAL 1000/V100131** | **Aceptado** | Evidencia en la verdad del ERP: el organizador periodifica la factura válida que llega después del cierre, incluso cuando la recibida en el mes fue rechazada (ACCR-API004289, V100039; ACCR-API004397, V100028). También periodifica a profesionales sin pedido fuera del conjunto «recurrente»: ACCR-API004242 (notaría V100129, 30/06), ACCR-API004008 (V100128), ACCR-API004324 (V100210). Todo REJECT del log tiene `corrected_by`.<br>API005253 (2026/047, 13/09) no tiene reemisión en septiembre. Se añade la periodificación por **270.793**: Dr 62300000 CC-1000-LEG 225.662 + Dr 63100000 CC-1000-LEG 45.131 / Cr 40090000 V100131. La imputación es la del histórico 2026/045–046. |
| **D2 · IC tránsito** | Mantengo | Solo 1000-1200 (IC1000-26-0042). Sin cambio. |
| **D3 · BOOK_AMOUNT_ERROR** | Mantengo | Sin cambio. |
| **D4 · V100147 en 1100 y 1000** | **Rechazado (se mantienen)** | Frecuencia de periodificación del organizador en los últimos 12 cierres (sep-25 a ago-26):<br>• V100147/1100: `XXXXXXX.XXX.` → 10/12<br>• V100147/1000: `X.XXXXXX...X` → 8/12<br>• V100147/1200: 8/12<br>• V100125/1000: 6/12, con 3 de los 4 últimos<br>La probabilidad de que exista la partida es > 50 %; quitarla cuesta más recall del que gana en precisión. |
| D5 · importes ACCRUAL | Mantengo | El evaluador confirma el método y los 3 importes exactos. |
| D6–D10 | Mantengo | Coincido con el evaluador. |

## Pasada propia adicional
- **Consumo doble de GR y sobrecompensación de GR/IR** en todos los asientos AP: después de E1 no hay ninguna GR usada dos veces ni ningún saldo 40090000 (sociedad, proveedor, pedido/pos) que exceda su partida abierta.
- **Rechazos sin reemisión en septiembre** (API005250, 5251, 5246, 5255, 5253, 5261): solo API005253 (V100131) y API005261 (ya periodificada como API004587) son servicios sin pedido. Los demás tienen pedido con entrada (GR/IR), así que no procede periodificar.
- **HOLD de proveedores periodificables**: ninguno. Los HOLD son de pedido (GR/IR) o de proveedores no dados de alta.
- **Recalibración del estimador** con la verdad: las periodificaciones del organizador siempre usan la factura futura real prorrateada. El backtest de agosto con media de 3 (34/45 claves dentro del ±15 %) sigue siendo el mejor de los probados (último valor, media de 2, de 6 y mediana). No cambio el método.

## Ficheros regenerados
- `ap.jsonl`: E1, E2, E5.
- `close.jsonl`: 83 filas (ACCRUAL 59, PREPAID 9, FX 8, BAD_DEBT 7). Cambian V100131, el redondeo de BAD_DEBT y el FX USD.
- `trial_balance_truth.jsonl` (257 filas), `trial_balance_recorded.jsonl` (251 filas, sin cambio) y `summary.json` (`close_entries` 83, CLOSE 83).

## Validaciones
- `make_je` sobre los 434 asientos de los 6 ficheros: sin errores.
- Cobertura de tasks: 100 % (297 / 25 / 34 / 12).
- `score.py phase_test phase_test phase_test/golden`: **100,00**.
- `trial_balance_recorded` = Σ diario (0 céntimos de diferencia).
- `trial_balance_truth` = recorded + todos los asientos del golden (0 céntimos); cada sociedad suma 0.
