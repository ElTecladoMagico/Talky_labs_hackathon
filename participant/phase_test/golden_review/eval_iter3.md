NOTA GLOBAL: 9,3/10

# Evaluación final del golden de test (septiembre 2026), iteración 3

Comparé `golden_review/snapshot_iter2/` con `golden/` fichero a fichero, repetí todas las validaciones globales e hice un backtest propio contra la verdad del organizador (el `CLOSE_ACCRUAL` del ERP, de oct-24 a ago-26). Los scripts están en `scratchpad/eval/`. No he modificado nada en `golden/`.

## 1. Diff real iteración 2 → iteración 3

| Fichero | ¿Cambia? | Detalle |
|---|---|---|
| ap.jsonl | Sí | Solo cambian las `lines` de 13 documentos no contabilizados (8 DUPLICATE, 3 HOLD, 2 REJECT). En ningún documento cambia otro campo ni las líneas de un documento contabilizado. Sigue sin líneas solo API005629 (proveedor no dado de alta). **No puntúa.** |
| close.jsonl | Sí | Las mismas 83 filas: no se añade ni se quita ninguna. Solo cambian 6 importes de luz, todos a «última factura × 0,5». Los recalculé uno a uno:<br>• 1000/V100029: 158.698 = 317.395/2<br>• 1100/V100028: 641.456 = (256.520 + 392.175 + 82.882 + 188.014 + 363.321)/2<br>• 1100/V100029: 989.884 = 147.086 + 200.174 (ciclos completos) + ½·(305.274 + 375.623 + 102.912 + 157.209) + ½·(171.382 + 172.848)<br>• 1200/V100028: 139.372 = 278.745/2<br>• 1300/V100029: 41.005 = 82.010/2<br>• 1910/V100028: 70.082 = 140.165/2 |
| trial_balance_truth.jsonl | Sí | Solo cambian 10 celdas: 62800000 y 40090000 de 1000, 1100, 1200, 1300 y 1910. Los deltas (+4.836, +47.637, +19.381, +3.933, +3.150) son exactamente los cambios de close. |
| ar_billing, ar_cash, bank_rec, ic, summary, trial_balance_recorded | No | Idénticos al snapshot. |

**No hay regresiones. Todo cambio está justificado.**

## 2. Validaciones globales (repetidas)
- `score.py` del golden contra sí mismo: **100,00**. El pipeline contra el golden da 95,80; solo se mueve close: 0,854 → 0,862.
- `make_je`: 434 asientos, 0 errores. Ids únicos, sin choques con el ERP.
- `trial_balance_recorded` = Σ diario: 0 céntimos. `trial_balance_truth` = recorded + todos los asientos del golden: 0 céntimos. Cada sociedad suma 0.
- AP: ninguna GR usada dos veces y ninguna GR/IR por encima de su partida abierta. Los chequeos de IVA, ISP, retenciones, garantía, socio y objeto de coste de la iteración 2 siguen limpios, porque los asientos de AP no han cambiado.

## 3. Decisiones del generador en la iteración 3

| Tema | Decisión del generador | Mi verificación independiente | Veredicto |
|---|---|---|---|
| **N1** (mi propuesta de 14/29) | Rechazada; se mantiene 0,5 | En los 23 cierres de luz del ERP, la parte del ciclo en curso es **siempre** 0,5 de la factura futura. La etiqueta depende del mes: «16/MM–30/MM» en los de 30 días, «17/MM–31/MM» en los de 31 y «14/02–28/02» en febrero. El análogo exacto, 30/09/2025, tiene «16/09–30/09» y 0,5 en 15 filas. | **El generador tiene razón: retiro N1.** Me equivoqué al deducir el inicio del ciclo de las facturas. |
| Recalibración de la luz (última × 0,5) | Adoptada | Mi backtest por suministro sobre todas las filas del organizador que periodifican el 50 %, con al menos 3 facturas previas recibidas antes del cierre: «última» acierta **154/243** dentro de ±15 % y «media 3» **140/243**. Coincide con su backtest por clave (el híbrido mejora 6 de 7 cierres y no empeora ninguno). | **Correcta.** Mejora esperada de 1–2 claves en close. |
| D2 (tránsito intragrupo solo 1000-1200) | Se mantiene | Coincide con mi análisis. Hay un único `IC_ACCRUAL` en todo el diario (el inyectado de julio). Las demás facturas IC de fin de mes llegan en 1–5 días y nunca se periodifican, ni siquiera IC1100-26-0002, que llegó el 19/03. | De acuerdo. Sigue siendo una apuesta sobre el par. |
| E5/N2 (`lines` en no contabilizadas) | Completado 13/14 | Revisé el diff: no toca nada más. | Cerrado (no puntúa). |

## 4. Última pasada en lo pendiente
- **Revisiones de precio (ar_billing)**: fecha = aprobación + 3 días (dev: 04/07; test: 04/09 sobre la aprobación del 01/09) y vencimiento a 30 días. Coherente con dev.
- **Redondeo de las periodificaciones de luz**: 1910/V100028 sale en 70.082 (redondeo hacia abajo de 70.082,5). El organizador usó 70.083 en agosto para el mismo importe. Es 1 céntimo, dentro de tolerancia e irrelevante para el balance (BAJO, informativo).
- No he encontrado nada más que no hubiera revisado ya en las iteraciones 1 y 2: AP partida a partida, bank_rec línea a línea, ar_cash, ic, PREPAID, FX y deterioro.

## 5. Notas por fichero y evolución

| Fichero | Peso | Iter. 1 | Iter. 2 | **Iter. 3** | Comentario |
|---|---|---|---|---|---|
| ap.jsonl | 30 % | 9,4 | 9,7 | **9,7** | Ningún error conocido. Las decisiones discutibles tienen evidencia fuerte. |
| ar_billing.jsonl | 10 % | 9,8 | 9,8 | **9,8** | Recalculado entero. |
| ar_cash.jsonl | 15 % | 9,4 | 9,4 | **9,4** | Dos aplicaciones discutibles (BL0000317, BL0000809). |
| bank_rec.jsonl | 20 % | 9,3 | 9,4 | **9,4** | La cobertura es completa. BOOK_AMOUNT_ERROR aparece en las casaciones y también en las partidas sin casar. |
| ic.jsonl | 5 % | 8,5 | 8,5 | **8,5** | Riesgo en el par del tránsito. |
| close.jsonl | 10 % | 7,0 | 7,6 | **7,9** | Estructura, conjunto de claves, objetos de coste, PREPAID, FX y deterioro: correctos. Los importes de periodificación son estimaciones calibradas; se espera que ~70–75 % caigan dentro de ±15 %. |
| trial_balance_* | 10 % | 9,6 | 9,7 | **9,7** | Coherente. Hereda el error de estimación de las periodificaciones. |
| summary.json | 0 % | 10 | 10 | **10** | — |
| **GLOBAL** | | **8,9** | **9,2** | **9,3** | Ponderado: 9,37. Se redondea a la baja por la incertidumbre irreducible. |

## 6. Hallazgos abiertos

| ID | Fichero | Sev. | Situación | Evidencia | Confianza en que el golden acierte |
|---|---|---|---|---|---|
| D5 | close | MEDIO (irreducible) | Importes de 59 filas ACCRUAL estimados; el organizador usa la factura real de octubre | Backtest por clave: 30–37 de cada 43–46 claves dentro de ±15 % | ~72 % por clave |
| D2 | ic | MEDIO (irreducible) | INVOICE_IN_TRANSIT solo en 1000-1200 (IC1000-26-0042); hay 5 facturas IC sin recibir | Patrón histórico: solo se marca el caso inyectado; test repite los pares de dev | ~70 % |
| D4 | close | BAJO | V100147 en 1000, 1100 y 1200 (proveedor irregular) | Presencia en 8–10 de los 12 cierres anteriores | ~70–80 % por clave |
| D1 | close | BAJO | V100131, 270.793 (factura rechazada sin reemisión en el mes) | Análogo exacto: ACCR-API004242 (V100129, 30/06) | ~80 % |
| D3 | bank_rec | BAJO | BOOK_AMOUNT_ERROR de BLC-2100 en las casaciones y también en las partidas sin casar | La política dice «lado libro»; dev solo pone en casaciones las causas de «diferencia» | Cobertura deliberada; pérdida máxima ~1 punto en una cuenta |
| D6/D7 | ar_cash | BAJO | BL0000317 → SU26-00098 (la más antigua con importe exacto); BL0000809 como duplicado completo de un parcial | Patrones de dev | ~80 % |
| D8/D9 | ap | BAJO | Imputación de API005184 (IC 1200→1100, OB-1100-2522.05); línea 47200000 SIMP en las `lines` de API004471 | Histórico del proveedor | ~85 % |
| R1 | close | BAJO (informativo) | Redondeo de 0,5 céntimos en 1910/V100028 | El organizador redondeó hacia arriba en agosto | Irrelevante |

**Recuento abierto: CRÍTICO 0, ALTO 0, MEDIO 2 (irreducibles), BAJO 6 (incluido R1). No queda ningún error seguro con impacto en la puntuación.**

Evolución de los hallazgos:
- Iteración 1: 1 ALTO, 4 MEDIO, 10 BAJO.
- Iteración 2: 0 ALTO, 2 MEDIO, 9 BAJO.
- Iteración 3: 0 ALTO, 2 MEDIO (irreducibles), 6 BAJO.

## 7. Veredicto final

**Sí, el golden está listo para usarse como referencia del equipo.**
- AP (30 %), ar_billing, ar_cash y bank_rec (en conjunto el 75 % del peso) están verificados partida a partida contra los documentos fuente, el ERP y la verdad de julio y agosto del organizador. No queda ningún error conocido.
- PREPAID, FX_REVAL y deterioro están recalculados de forma independiente y son exactos.
- La coherencia interna (balances, `make_je`, cobertura y formato) es perfecta.

**Partidas de baja confianza al puntuar contra él.** Una discrepancia del pipeline en estas partidas no implica necesariamente un error del pipeline:
1. **close / ACCRUAL**: todas las importes de periodificación, en especial las volátiles:
   - V100125 (consultoría, 1000);
   - V100145 (viajes, 1000/1100/1200);
   - V100147 (material de oficina, presencia incierta);
   - V100131 (depende de una reemisión futura).
   Conviene leer el score de close con un margen de ±0,1.
2. **ic / INVOICE_IN_TRANSIT 1000-1200**: el par elegido es una apuesta informada.
3. **bank_rec / BLC-2100**: la doble anotación del BOOK_AMOUNT_ERROR (afecta a la F1 de una cuenta).
4. **ar_cash**: BL0000317 (elección por antigüedad) y BL0000809 (duplicado de un parcial).
5. **trial_balance**: hereda el error de las periodificaciones. Diferencias de unos pocos miles de euros contra el balance del organizador son esperables.
6. **Casos de AP decididos por deducción**, con evidencia fuerte pero sin confirmación directa del organizador. Son útiles para medir el pipeline, pero conviene tratarlos como casos de criterio:
   - API005261 (destinatario erróneo);
   - API004877 (pedido citado erróneo);
   - API005236 (duplicado de un escaneo con OCR);
   - API004780 y API005012 (PRICE_VARIANCE frente a certificación a origen);
   - API005184 (imputación);
   - las convenciones de formato heredadas de dev: cabecera en moneda del documento y abonos en positivo.
