NOTA GLOBAL: 8.9/10

# Evaluación del golden de test (septiembre 2026), iteración 1

Evaluador independiente. Scripts propios en `scratchpad/eval/` (`apdiff.py`, `apchk.py`, `dup.py`, `rules.py`, `pogr.py`, `jechk.py`, `desc.py`, `coding.py`, `baddebt.py`, `icbal.py`, `tbchk.py`). No he modificado nada en `golden/`.

## 0. Método y fuentes de verdad usadas

Además de las políticas y del golden de dev, he usado una fuente que el generador solo usó en parte: **el ERP de test contiene la verdad del organizador de julio y agosto**.
- `ap_document_log.jsonl` incluye decisión, motivo y `corrected_by` de cada documento de julio y agosto.
- `journal_entries.jsonl` incluye los asientos `CLOSE_ACCRUAL` de 31/07 y 31/08. Su asignación `ACCR-<doc_id>` dice qué factura futura y qué objeto de coste usa el organizador.
- También están los `CLOSE_FX`, `CLOSE_PREPAID`, `IC_ACCRUAL`, `CASHAPP` y los préstamos.

Con eso he contrastado la imputación, el criterio de periodificación, la valoración FX, la provisión y el intragrupo. La comparación con `submission/test` (95,83 frente a este golden) sirvió para localizar discrepancias. Ninguna se ha resuelto "por mayoría": cada una tiene su evidencia abajo.

Comprobaciones globales superadas:
- `score.py` del golden contra sí mismo: 100. El formato es válido.
- Todos los asientos cuadran por sociedad.
- `trial_balance_recorded` es igual a Σ del diario: 0 céntimos de diferencia en 251 filas.
- `trial_balance_truth` es igual a recorded más todos los asientos del golden, sumados como `score_tb`: 0 céntimos. Cada sociedad suma 0.
- `summary.json` es coherente con los recuentos (AP 231 = POST + PPB; IC 2 = WTP + DUP, mismo criterio que dev).

## 1. Notas por fichero

| Fichero | Peso score.py | Nota | Comentario |
|---|---|---|---|
| ap.jsonl | 30 % | **9,4** | 297/297. No he encontrado ningún error de decisión. Un error seguro de imputación, pedido y asiento (API004877) y detalles no puntuables. |
| ar_billing.jsonl | 10 % | **9,8** | Recalculado de forma independiente: importes, IVA, retenciones, 5 al millar, amortización del anticipo, DIR3, vencimientos y fechas PPA/mercado. Todo coincide. |
| ar_cash.jsonl | 15 % | **9,4** | 34/34 coherentes con referencias N43, avisos de pago, FACe y partidas abiertas. Un caso con elección por antigüedad (BL0000317) y el tratamiento del duplicado de un parcial (BL0000809) son discutibles. |
| bank_rec.jsonl | 20 % | **9,3** | Cobertura del 100 % de las líneas del extracto. Las diferencias de casación son las esperadas. Categorías y ajustes contrastados con la política y la verdad de agosto. Discutible: BOOK_AMOUNT_ERROR duplicado en match y unmatched. |
| ic.jsonl | 5 % | **8,5** | 4 causas correctas por evidencia. El riesgo está en qué factura en tránsito (o cuántas) marca el organizador. |
| close.jsonl | 10 % | **7,0** | PREPAID, FX_REVAL y BAD_DEBT recalculados: exactos (dentro de ±1 €). ACCRUAL: la estructura es correcta, los importes son estimaciones y falta probablemente una partida (V100131). |
| trial_balance_* | 10 % (derivado) | **9,6** | Internamente perfecto. Solo hereda los errores de los asientos (API004877 y los importes de periodificación). |
| summary.json | 0 % | 10 | — |

Ponderado: 0,30·9,4 + 0,10·9,8 + 0,15·9,4 + 0,20·9,3 + 0,05·8,5 + 0,10·7,0 + 0,10·9,6 = **9,12**. Lo rebajo a **8,9** por la incertidumbre irreducible del cierre y del intragrupo: el organizador conoce las facturas futuras y nosotros no.

## 2. Hallazgos

### 2.1 Errores seguros

| ID | Fichero | Sev. | Qué hay | Qué debería haber | Evidencia | Conf. |
|---|---|---|---|---|---|---|
| E1 · API004877 | ap | **ALTO** | POST con pedido 4500022762/10 (ensayos de compactación, OB-1100-2520) y GR 1000033674. Asiento: Dr 40090000 312.754 + Dr 62300000 5.997 OB-1100-2520.05 «diferencia de precio» + 472 66.938 / Cr 41000000 385.689 | Pedido **4500022726/10** («Levantamiento topográfico y replanteo», 318.751 €, **OB-1100-2419.05**), SES **1000033672** (15/09, 318.751, sin usar). Línea: 318.751, 62300000, PEP OB-1100-2419.05, S21. Asiento: Dr 40090000 318.751 V100020 asig. 4500022726/10 + Dr 47200000 66.938 / Cr 41000000 385.689. Sin línea de diferencia. | La factura TKD26/28754 describe «Levantamiento topográfico y replanteo» y cita por error el pedido de API004879. La SES 1000033674 queda consumida dos veces: la usan API004877 y API004879 (TKD26/28757, que sí es «Ensayos de compactación» por 3.127,54 = pedido). El open item de 40090000 V100020 4500022762/10 es −312.754 y el golden lo carga por 625.508 (sobrecompensación). Es el único caso de los 300 pares de 40090000 que excede su partida abierta. Patrón PO_REF_TYPO de dev y P1 («entrada inequívoca bajo otro pedido del mismo proveedor»). | 95 % |
| E2 · API005260 | ap | BAJO (no puntúa) | `company` 1100 (la destinataria del papel) | `company` **1200**. La convención de dev para WRONG_ADDRESSEE es poner la sociedad correcta (API005225 de dev: papel a 1100, golden 1200). La reemisión API004762 va a 1200 (CC-1200-RR02). | dev ap.jsonl | 85 % |
| E3 · BAD_DEBT C200080 | close | BAJO | target 60.174.054, amount 35.497.752 (redondeo del 50 % hacia arriba) | 60.174.053 / 35.497.751. El organizador trunca el 50 %: provisiones previas 39.639 (de 79.279), 44.779, 25.499 y 141.802. | `baddebt.py`. Dentro de tolerancia (±1 €), 1 céntimo en el balance. | 90 % |
| E4 · FX_REVAL BANK:BANH-3100-USD | close | BAJO | −9.112.164 | −9.112.159, coherente con los ajustes de comisiones del propio bank_rec (28.898 + 8.027 + 41.910 = 78.835). El golden usa un valor contable 5 céntimos distinto. | Valor contable 182.638.033 − 78.835; 10.346.300 × 16,764161 = 173.447.039. Dentro de tolerancia. | 80 % |
| E5 · HOLD/REJECT/DUPLICATE sin `lines` | ap | BAJO (no puntúa) | `lines: []` | En dev el golden las trae codificadas. | dev ap.jsonl | 90 % |

### 2.2 Discutibles (recomendación entre paréntesis)

| ID | Fichero | Sev. | Situación | Opinión | Conf. de que haya que cambiar |
|---|---|---|---|---|---|
| D1 · ACCRUAL 1000/V100131 | close | **MEDIO** | No hay periodificación para la notaría. API005253 (servicio 13/09, 2.707,93 €) se rechaza por WITHHOLDING_MISSING sin reemisión en septiembre. | **Añadir** ACCRUAL 1000/V100131 por **270.793**: Dr 62300000 CC-1000-LEG 225.662 y Dr 63100000 CC-1000-LEG 45.131 (suplidos SEX) / Cr 40090000 V100131. Precedente de dev: los rechazos de servicios sin pedido cuya reemisión llega el mes siguiente se periodifican completos (API004289/V100039, API004397/V100028). El propio `golden_patterns_dev.md` lo documenta. `ap_document_log` muestra que todo REJECT tiene `corrected_by`. La política incluye «consultores y profesionales sin pedido». La imputación sale del histórico de V100131 (API004478, API004721). | 60 % |
| D2 · IC tránsito | ic | MEDIO | Solo se marca 1000-1200 (IC1000-26-0042). Hay 5 facturas IC del 30/09 sin recibir: 0042 (1200), 0043 (1300), 0044 (2100), 0045 (3100) e IC1100-26-0009 (1910). | **Mantener**. En may, jun y ago, todas las IC recibidas en los primeros días del mes siguiente quedaron sin IC_ACCRUAL. En julio solo se marcó la recibida el 17/08 (la inyectada). Test repite los pares de dev en WTP, DUP y POOL. Riesgo residual: otro par o ninguno. | 25 % |
| D3 · BOOK_AMOUNT_ERROR BLC-2100 | bank_rec | BAJO | El par BL0003162 ↔ 2100-2026-1600000188#2 aparece como match y también en unmatched_book | **Mantener**: es una cobertura razonable. Precedente de dev: las causas de tipo «diferencia» van solo en match. La política dice lado «libro». Pérdida máxima ≈ 1 punto de F1 en una cuenta. El ajuste de 90 céntimos (transposición 56.366,55 / 56.365,65) es correcto. | 40 % |
| D4 · ACCRUAL 1100/V100147 (150.728) | close | MEDIO | Proveedor irregular: 1100 facturó en ene–mar y may–jul, no en agosto. La verdad de agosto no lo periodificó. | Moneda al aire (presencia aproximada del 70 %). Si la entrega es para puntuar, quitarlo reduce el riesgo de falso positivo. Igual con 1000/V100147 (4 de 8 meses). | 50 % |
| D5 · Importes ACCRUAL | close | MEDIO | Estimaciones: mensuales con media de 3 meses, luz al 50 % del ciclo, agua 30/61 del bimestre. | El método es correcto y coincide con la mecánica del organizador (factura real futura prorrateada por días). Error esperado: ~25 % de las claves fuera de ±15 % (backtest de agosto 34/45). Fracción de luz 0,5 frente a 14/29: inmaterial (3,5 %). Los casos exactos (V100029/1100 obras 2515 y 2524 por API004852 y API004916, V100034/1100 79.012 por API004587) están **confirmados** por la verdad de agosto: esas facturas no están en el inbox de test. | — |
| D6 · BL0000317 | ar_cash | BAJO | Aplicado a SU26-00098 | **Mantener**. BL0000316 cita SU26-00081 (parcial del 60 %). BL0000317 sin referencia: la factura abierta más antigua por importe exacto es SU26-00098. | 20 % |
| D7 · BL0000809 | ar_cash | BAJO | OVERPAYMENT_DUPLICATE por el importe completo (9.612.198). Es la repetición de BL0000222, que era un parcial del 60 % de SU26-00112. | **Mantener**. Patrón de dev: «PAGO <fra>» sin ref1 e importe idéntico al cobro anterior. La alternativa (aplicar 6.408.133 y 3.204.065 como exceso) no tiene precedente. | 20 % |
| D8 · API005184 | ap | BAJO | IC 1200→1100 «limpieza final Hotel Mirador», imputada a 62900000 OB-1100-2522.05 | **Mantener**. OB-1100-2522 es el Hotel Mirador (projects.jsonl). El histórico de V-IC1200 en 1100 usa 62900000 al PEP `.05`. | 15 % |
| D9 · API004471 | ap | BAJO | `lines` incluye una línea 47200000 SIMP (IVA de importación suplido) y la cabecera tiene net = 3.753.440, tax 0 | **Mantener**. Coincide con el histórico de V100122 (ap_invoices con tax 0 y asiento 1100-2026-5100000499 con la misma estructura). No hay precedente en el golden de dev. | 20 % |
| D10 · Parciales «raros» | ar_cash | BAJO | BL0000687 al 50 %, BL0000546 (PPA) al 75 % | **Mantener**: aplicar lo cobrado. Comprobé que la factura PPA es correcta: 14.498,955 MWh × 70 % truncado × 41,50 = 421.194,62. El histórico de cobros PPA es siempre completo, pero el importe facturado está bien calculado, así que es un parcial. | 15 % |

### 2.3 Recuento por severidad
- Seguros: ALTO 1 (E1), BAJO 4 (E2–E5).
- Discutibles: MEDIO 4 (D1, D2, D4, D5), BAJO 6 (D3, D6–D10).
- Total: CRÍTICO 0, ALTO 1, MEDIO 4, BAJO 10.

## 3. Verificaciones independientes realizadas (todas sin hallazgos, salvo los ya citados)

**AP (297)**
- Tipo de documento, NIF del emisor → proveedor y NIF del destinatario → sociedad. Número normalizado, fecha y moneda contra la extracción. Importes contra PDF y XML (en MX, la retención del PDF).
- Aritmética de cabecera: net + tax = gross y payable = gross − ret − garantía.
- Duplicados contra `ap_invoices`, `ap_document_log` y el propio mes: los 14 DUPLICATE y su `duplicate_of` correctos. Los 2 fraudes con mismo número (5263/5264) son HOLD, según el precedente API005230 de dev. Las 11 reemisiones de REJECT en el mes y API004368 (reemisión de un rechazo de agosto) son POST.
- REJECT: ISP (3 subcontratas con IVA), tipo de IVA (prefabricado y laboratorio al 10 %, agua al 21 %), retención (notaría IRPF15, arrendamiento IRPF19), aritmética (2), certificación a origen (2), CFDI (XML incoherente, igual que dev API005228), NIF ausente (1), destinatario (3).
- API005261 confirmado como WRONG_ADDRESSEE:
  - contrato AB-601305, distinto del de la UTE (AB-683586, API004710);
  - la verdad de agosto periodifica V100034/1100 jul–ago por 79.012 con ACCR-API004587, exactamente su base;
  - el id está en el rango 52xx de los documentos inyectados;
  - el recuento de 3 WA coincide con la plantilla de dev.
- HOLD QTY (10): todos tienen algún albarán sin entrada. Ninguno tiene una entrada alternativa inequívoca.
- HOLD PRICE (6): todos superan el 2 % o 150 €. En particular, API004780 y API005012 facturan la medición del mes a precio superior al del pedido, no el importe a origen, así que se corrige el criterio del pipeline.
- Recuperaciones PO_REF (4684, 4576, 4663, 4674, 4695): entradas que casan cantidad e importe.
- API004601 por la secuencia de numeración de V100022: 0007999, 0008026 y 0008077 van a 4500018610.
- PPB (3): certificados nuevos emitidos después de la fecha de factura.
- Payee: factor V100013/V100092 por ficha y V100006 desde el 09/09 (API004870). El embargo de V100114 se recibió después de API004699, así que payee es null.
- **Asientos**: los 231 cuadran. Proveedor = payable. 472 = cuota. 4751 = retención. 400009 = garantía. Toda GR/IR está dentro de su partida abierta 40090000, salvo E1. Pedido, proveedor y sociedad coherentes. Cuenta, objeto y código fiscal iguales a los de la posición del pedido.
- **Imputación sin pedido**: los 55 documentos de test que aparecen en `ACCR-<doc>` de las periodificaciones del organizador (jul/ago) coinciden al 100 % en cuenta y objeto con el golden. Eso confirma luz V100028/V100029 (incluidos 4814/4880/4903/4969), agua y el canon a 63100000.
- Resto contra el histórico del proveedor: sin discrepancias.
- Abonos: misma cuenta y objeto que la factura original (vía posición de pedido).
- FX: SYN-BCE de la fecha de factura y cruce EUR para USD→MXN, al céntimo.

**AR billing**: recalculados los 25 conceptos, entre ellos:
- certificaciones (todas CONFORME, por tanto 0 SKIP y 0 WIP);
- RISP y PT con garantía del 5 %;
- MX con 5 al millar y anticipo al 30 % (saldos de 438 suficientes);
- servicios con extraordinarios conformes (PJ01 excluye OT-2026-998 pendiente);
- revisiones de 8 meses;
- PPA y mercado. Las fechas PPA y mercado (día 3 y día 6, o el siguiente hábil) se confirman con el histórico de enero a agosto de 2026.
- DIR3 iguales al maestro solo para clientes públicos ES. 430 = payable. Numeración EN26-00017/18 coherente con los cobros del mes.

**AR cash**: cada cobro contrastado con ref1/ref2/detalle N43, avisos de pago (7), FACe (3) y partidas abiertas. El NETTING_AP se cruza con la factura de honorarios API004774 (26012027, 828.850). El patrón de netting de jun–ago está en el ERP.

**Bank rec**:
- Cobertura: todas las líneas del extracto de septiembre una sola vez, en 12 cuentas.
- Diferencias de importe solo en los pares categorizados (FX ×5, LOAN 1, BOOK_AMOUNT 1, y USD/MXN en la cuenta USD).
- Los 8 PRIOR_PERIOD tienen su cargo en los extractos de agosto.
- Los intereses trimestrales de préstamos sindicado y project finance van a 66200000. Así se contabilizaron T1 y T2.
- Comisión de aval a 66900000.
- Los DD solo se ajustan contra facturas POST, con asignación correcta.

**IC**: los saldos de 55200000 entre 1000↔1100/1200/2100 cuadran a 0 tras los ajustes. Intereses KMI-2025-01 de septiembre: ambas partes 2.500.000 EUR (30 días), así que no hay INTEREST_DAY_COUNT. La partida duplicada IC1000-26-0034 sigue abierta en 2100 (403).

**Close**:
- PREPAID: fórmula floor verificada en los 9 contra la serie `CLOSE_PREPAID`. No hay primas, rústicos ni cuotas anuales nuevas en septiembre.
- FX_REVAL: mismos 8 tipos de partida que la verdad de agosto (los AP USD de agosto ya están pagados; anticipos y abonos USD no se valoran).
- BAD_DEBT: recalculado cliente a cliente con vencidos >180/>365 días, concurso C200004 ya provisionado al 100 % y provisión previa en 49000000. Coinciden los 7 movimientos y no falta ninguno.
- No hay concursos nuevos (no procede DOUBTFUL_RECLASS).

## 4. Opinión sobre las dudas abiertas del generador

1. **IC tránsito**: de acuerdo con marcar solo 1000-1200 (ver D2). Añadir las otras 4 costaría 4 falsos positivos en la F1 de detección si el organizador sigue su patrón.
2. **BOOK_AMOUNT_ERROR en match y unmatched**: de acuerdo (ver D3).
3. **API005261**: de acuerdo, ahora con evidencia fuerte. Contrato distinto del de la UTE y periodificación de agosto ACCR-API004587 por 79.012, que la convierte en la factura de 1100 mal dirigida.
4. **Periodificaciones**:
   - V100147/1100: dudosa (D4).
   - V100125: mantener la media; es volátil y ningún método acertará con fiabilidad.
   - Fracción 0,5 frente a 14/29: irrelevante.
   - **Falta V100131** (D1). Aplicad la misma regla que ya usáis para V100034 y API004587.
5. **tagged**: no puntúa. Ignorar.
6. **MULTI_PO**: no hay en test. Mi comparación descripción ↔ pedido sobre todas las líneas con pedido solo encontró API004877, que es un caso de pedido citado erróneo (E1), no MULTI_PO. Proveedores no dados de alta sin periodificación: correcto según dev.

## 5. Acciones para la iteración 2 (por impacto)
1. Corregir **API004877** (E1): líneas, pedido, GR, asiento y, en consecuencia, los balances.
2. Decidir **D1** (añadir ACCRUAL 1000/V100131 por 270.793). Recomiendo añadirlo.
3. Revisar D4 (V100147/1100 y 1000).
4. Cosméticos: E2 (company 1200 en API005260), E3 (redondeo floor en BAD_DEBT C200080), E4 (FX del banco USD coherente con bank_rec), E5 (lines en no contabilizados).
5. Regenerar `trial_balance_truth.jsonl` y `summary.json` tras los cambios.
