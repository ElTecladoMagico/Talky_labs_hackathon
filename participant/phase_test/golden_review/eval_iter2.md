NOTA GLOBAL: 9,2/10

# Evaluación del golden de test (septiembre 2026), iteración 2

Re-evaluación completa, no solo de los cambios. Los scripts están en `scratchpad/eval/`: los de la iteración 1, reejecutados sobre el golden nuevo, y los nuevos `taxchk.py` y algunas comprobaciones en línea. No he modificado nada en `golden/`.

## 0. Integridad y regresiones

No hay copia de la versión anterior del golden en el scratchpad, así que he detectado regresiones de dos formas:
- reejecutando todos los chequeos de la iteración 1;
- comparando con el pipeline, que es una referencia fija.

| Control | Resultado |
|---|---|
| `score.py` del golden contra sí mismo | **100,00** |
| `make_je` (de `common/je.py`) sobre los 434 asientos de los 6 ficheros | 0 errores |
| Ids de asiento únicos, sin choque con el diario del ERP; `je` = `journal_entry.id` en close | OK |
| `trial_balance_recorded` = Σ diario | 0 céntimos (251 filas) |
| `trial_balance_truth` = recorded + todos los asientos, sumados como `score_tb` | 0 céntimos (257 filas); cada sociedad suma 0 |
| `summary.json` | close_entries 83 y CLOSE 83, coherentes |
| Pipeline contra golden, iteración 1 → iteración 2 | AP 0,9254 → 0,9236 (solo cambia API004877; la lista de discrepancias pasa de 79 a 80 líneas, sin otras variaciones). Close 0,860 → 0,854 (V100131 y redondeos). ar_billing, ar_cash, bank_rec, ic y balance sin cambios. |
| GR consumidas dos veces / 40090000 por encima de su partida abierta | 0 / 0 |

**No hay regresiones.**

## 1. Notas por fichero

| Fichero | Peso | Iter. 1 | **Iter. 2** | Motivo |
|---|---|---|---|---|
| ap.jsonl | 30 % | 9,4 | **9,7** | E1 corregido. En la nueva pasada partida a partida (IVA, ISP, retenciones, garantía, socio, objeto de coste y beneficiario) no hay errores. |
| ar_billing.jsonl | 10 % | 9,8 | **9,8** | Sin cambios. Los asientos tienen los mismos objetos (cuenta, socio, objeto de coste y código fiscal) que el golden de dev para los mismos contratos. |
| ar_cash.jsonl | 15 % | 9,4 | **9,4** | Sin cambios. Cliente de cada aplicación igual al de la factura; pagaré y cesión verificados. |
| bank_rec.jsonl | 20 % | 9,3 | **9,4** | Sin cambios. Nuevo: el 100 % de las líneas 572 de septiembre del libro están casadas o clasificadas, y cada recibo domiciliado ajustado cita en el N43 la factura correcta. |
| ic.jsonl | 5 % | 8,5 | **8,5** | Sin cambios. Riesgo residual en la elección del par en tránsito. |
| close.jsonl | 10 % | 7,0 | **7,6** | Se añade V100131 y se aplica el truncado del 50 % en el deterioro. Los objetos de coste de las periodificaciones coinciden al 100 % con la verdad de agosto. Quedan las estimaciones y la fracción de la luz (N1). |
| trial_balance_* | 10 % | 9,6 | **9,7** | Coherente. Solo hereda la incertidumbre de las periodificaciones. |
| summary.json | 0 % | 10 | 10 | — |

Ponderado: 0,3·9,7 + 0,1·9,8 + 0,15·9,4 + 0,2·9,4 + 0,05·8,5 + 0,1·7,6 + 0,1·9,7 = **9,33**. Lo dejo en **9,2** por la incertidumbre que no se puede eliminar: la factura futura en las periodificaciones y el tránsito intragrupo.

## 2. Estado de los hallazgos de la iteración 1

| ID | Sev. | Estado | Verificación |
|---|---|---|---|
| E1 · API004877 | ALTO | **Resuelto** | Línea 318.751 / 62300000 / OB-1100-2419.05 / S21 / pedido 4500022726-10 / GR 1000033672. Asiento: Dr 40090000 318.751 (V100020, 4500022726/10) + 47200000 66.938 / Cr 41000000 385.689. API004879 conserva 4500022762-10 / GR 1000033674 / OB-1100-2520.05. Ninguna GR se usa dos veces y no hay sobrecompensación. |
| E2 · API005260 company | BAJO | **Resuelto** | company = 1200. |
| E3 · BAD_DEBT, redondeo | BAJO | **Resuelto y generalizado** | C200080 35.497.751, C200038 14.065 (28.131 // 2), C200058 10.229 (20.459 // 2). Coincide con la regla de truncado que muestran las provisiones previas del organizador. Los otros 4 clientes no cambian. |
| E4 · FX BANK:BANH-3100-USD | BAJO | **Resuelto** | −9.112.159, coherente con los ajustes de comisiones del bank_rec. |
| E5 · `lines` en no contabilizadas | BAJO | **Parcial** (no puntúa) | 228 + 3 contabilizadas con líneas. HOLD 16/20, REJECT 15/17 y DUPLICATE 6/14 con líneas. Sin líneas: 4 HOLD, 2 REJECT y 8 DUPLICATE de originales del histórico. Sin impacto en la nota. |
| D1 · ACCRUAL 1000/V100131 | MEDIO | **Resuelto** | 270.793: Dr 62300000 CC-1000-LEG 225.662 + 63100000 CC-1000-LEG 45.131 / Cr 40090000 V100131. **Evidencia reforzada**, verificada por mí: el organizador periodificó el 30/06 la notaría V100129 (ACCR-API004242, 457.067). Esa factura del 25/06 fue rechazada en julio (API005223, MANDATORY_FIELD_MISSING, `corrected_by` API004242). Es el mismo caso. Más precedentes de profesionales sueltos: V100128 a 31/05 y V100210 a 30/06. Mi confianza en que la partida es correcta sube al 80 %. |
| D2 · IC tránsito solo 1000-1200 | MEDIO | Sin cambios (de acuerdo) | Misma opinión. |
| D3 · BOOK_AMOUNT_ERROR en match y unmatched | BAJO | Sin cambios (de acuerdo) | Misma opinión. |
| D4 · V100147 (1100 y 1000) | MEDIO | **Rechazo del generador aceptado** | He verificado su evidencia en `CLOSE_ACCRUAL` de los últimos 12 cierres: 1100/V100147 `XXXXXXX.XXX.` (10/12), 1000/V100147 `X.XXXXXX...X` (8/12), 1200/V100147 8/12. Con una presencia del 67–83 %, mantener la partida maximiza la F1 esperada. Retiro el hallazgo. |
| D5 · importes estimados | MEDIO | Sin cambios | Se mantiene, salvo el ajuste de fracción N1. |
| D6–D10 | BAJO | Sin cambios (de acuerdo) | — |

## 3. Pasada nueva y más profunda (hallazgos nuevos)

### 3.1 AP partida a partida (231 asientos en moneda local y en divisa)
- **IVA**: el 472 por código es igual a round(base de las líneas × tipo) en todos los casos.
- **ISP** (SISP, SIC, SIS, PAUT, PSIS): pares 47210000/47710000 = round(base × 21 % o 23 %), sin excepciones.
- **Retenciones** (IRPF15, IRPF19, PTIRS25, MXFLETE): 47510000 = tipo × base sin suplidos. Ningún proveedor sin retención en ficha lleva 47510000.
- **Garantía**: 40000900 = 5 % de la base para todos los proveedores con `guarantee_retention_bp`. Los dos abonos de subcontrata (API005611 y API005613) van sin garantía; es la convención de dev (API005589 y API005586), así que es correcto.
- **Socio**: 40090000, 40000900, 40000000, 41000000 y 40300000 llevan siempre `partner` = proveedor.
- **Objeto de coste**: ninguna línea 6xx, 7xx o 2xx sin centro de coste o PEP.
- **Imputación de suministros**: todas las facturas de luz, agua, telecomunicaciones, combustible y residuos están confirmadas por referencias `ACCR-<doc>` del organizador. Solo quedan sin referencia el profesional API004947 y 4 abonos, que ya están verificados contra su factura original.
- **Duplicados encubiertos**: busqué mismo proveedor, importe y fecha con distinto número. Los únicos casos (V100023 F2636270/F2636286, V100021, V100022) son alquileres recurrentes de obras distintas con pedidos distintos, así que son legítimos.
- **Beneficiario del pago** (factor V100013/V100092/V100006, embargo) y **dominios del correo**: sin anomalías.

### 3.2 bank_rec línea a línea
- Todas las líneas del diario en 57200001…06 de septiembre de las 12 cuentas están casadas o en `unmatched_book`. No falta ni sobra ninguna.
- Ninguna casación usa una línea del libro anterior a septiembre.
- Los 10 recibos domiciliados ajustados citan en el detalle del N43 (`FRA …`) exactamente la factura de la asignación del ajuste.
- El cargo duplicado BL0005776 lleva la misma referencia y mandato que BL0001960 (FV-2026-03545), así que BANK_ERROR es correcto.
- El barrido BL0005740 tiene ref1 CP2609221200, coherente con el POOLING_NOT_BOOKED del intragrupo.

### 3.3 ar_cash y ar_billing
- **ar_cash**: cada aplicación pertenece al cliente y la sociedad del cobro. El pagaré 3287513 (C200006, vencimiento 21/09) cuadra. OB26-00073 está marcada `factored: true`.
- **ar_billing**: los asientos repiten exactamente los objetos (cuenta, socio, objeto de coste y código fiscal) del golden de dev para los mismos contratos. La única diferencia en cabecera es `face.registry`, que no puntúa.

### 3.4 Periodificaciones contra la verdad de julio y agosto
- **Conjunto de claves**: todas las claves que el organizador periodifica 12 de 12 meses están en el golden.
  - Excluidas con razón: las que dejó de periodificar (1100/V100036 y 1100/V100038, sin partidas desde hace 6 y 8 meses) y los profesionales esporádicos (V100128, V100129 y V100210, 1–2 de 12).
  - Incluida con razón: V100131.
- **Objetos de coste por clave**: idénticos a los de la periodificación de agosto, incluido el canon 63100000 del agua de 1910.
- **Sin doble conteo**: las facturas del ciclo 17/08–15/09 recibidas en septiembre ya están contabilizadas. Las que siguen sin llegar (API004852, API004916 y API004587, que no están ni en el histórico ni en el log) se periodifican completas.

### 3.5 Hallazgos nuevos

| ID | Fichero | Sev. | Qué hay | Qué debería haber | Evidencia | Conf. |
|---|---|---|---|---|---|---|
| N1 · fracción de la luz | close | BAJO | Periodificaciones de V100028 y V100029 al 50 % de un ciclo 16/09–15/10 (period `2026-09-16…30`) | **14/29 = 48,28 %**, porque el ciclo del organizador empieza siempre el día 17: 17/09–15/10, 29 días, de los que 14 caen en septiembre | Facturas de septiembre con periodo «17/08/2026 – 15/09/2026». Periodificaciones del organizador etiquetadas «17/07–31/07» y «17/08–31/08», con exactamente el 50 % de un ciclo de 30 días (API004814: 152.636 = 305.274/2). Hay un sesgo sistemático de +3,6 % en unas 15 filas. No cambia el formato, pero consume margen de la tolerancia del ±15 % en un estimador que ya tiene error. Excepción: el «ciclo completo» de API004852 y API004916 es correcto. | 70 % |
| N2 · `lines` restantes | ap | BAJO (no puntúa) | 14 documentos no contabilizados sin `lines` | Opcional | Ver E5 | — |

No he encontrado nada crítico, alto ni medio nuevo.

## 4. Recuento
- Iteración 1: 6 resueltos (E1, E2, E3, E4, D1, D4 retirado), 1 parcial (E5) y 7 discutibles mantenidos de acuerdo con el generador (D2, D3, D5–D10).
- Abiertos ahora:
  - Seguros: BAJO 1 (E5/N2, no puntúa).
  - Discutibles: MEDIO 2 (D2 IC tránsito, D5 estimaciones de periodificación), BAJO 8 (N1, D3, D6–D10).
- **Total abiertos: CRÍTICO 0, ALTO 0, MEDIO 2, BAJO 9.**

## 5. Recomendaciones para la iteración 3
1. **N1**: aplicar la fracción 14/29 a la parte de septiembre de los ciclos de luz. Afecta a V100028 en 1100, 1200 y 1910 y a V100029 en 1000, 1100 y 1300; no a las partidas «ciclo completo». Después, regenerar los balances.
2. Opcional: terminar E5. No puntúa.
3. Por lo demás, el golden está listo: ningún cambio pendiente tiene impacto material en la puntuación.
