# Golden de test — notas del generador, iteración 3 (final)

Antes de tocar nada copié el golden de la iteración 2 en `golden_review/snapshot_iter2/` (9 ficheros) para que se pueda hacer diff.

## Hallazgos → decisión → cambio

| ID | Decisión | Evidencia y cambio |
|---|---|---|
| **N1 · fracción de la luz (14/29)** | **Rechazado; se mantiene 0,5** | En los 23 cierres de `CLOSE_ACCRUAL` de V100028/V100029 (oct-24 a ago-26), la parte del ciclo en curso es **siempre exactamente el 50 %** de la factura, cualquiera que sea la longitud del mes. En los meses de 30 días el organizador etiqueta el periodo **«16/MM–30/MM»** con fracción 0,5 (2024-11, 2025-04, 2025-06, **2025-09**, 2025-11, 2026-04, 2026-06); en los de 31 días, «17/MM–31/MM» y 0,5; en febrero, «14/02–28/02» y 0,5. El análogo exacto de septiembre de 2026 es el 30/09/2025: «16/09–30/09», 0,5 (15 filas). Con 14/29 todas las filas saldrían un 3,4 % por debajo. Se mantiene 0,5 y el periodo `2026-09-16…2026-09-30`. |
| **D5 · importes de las periodificaciones** | **Recalibrado (solo la luz)** | Detalle en la sección de calibración. La luz pasa a estimarse con la **última factura del suministro** × 0,5; antes era la media de 3. El resto sigue con la media de 3. |
| **D2 · tránsito intragrupo** | **Se mantiene** (solo 1000-1200) | Nueva evidencia en el log (2024-10 a 2026-08): de unas 110 facturas IC de fin de mes, casi todas llegan entre los días 1 y 5 del mes siguiente sin `IC_ACCRUAL`. Hay **un único `IC_ACCRUAL` en todo el diario** (31/07/2026, 1200, IC1000-26-0032, el escenario inyectado de dev). Incluso IC1100-26-0002, que llegó el 19/03/2026, no se periodificó en febrero: el organizador solo marca el caso inyectado. Las demás causas de test repiten los pares de dev, así que la mejor apuesta sigue siendo 1000-1200. |
| **E5/N2 · `lines` en no contabilizadas** | **Completado** (no puntúa) | De los 14 documentos pendientes se completan 13:<br>• 8 DUPLICATE de originales del histórico: líneas reconstruidas desde el asiento del original (GR/IR → posición de pedido; gasto directo → cuenta y objeto), con los importes del duplicado salvo en API005236, cuyo OCR descuadra y se usan los del original;<br>• API004771: posición 4500020094/10 más correctivo al mismo objeto (62200000 CC-1300-PSF1);<br>• API004562: posición por albarán con GR (4500018110 / 4500018422) y por descripción en los 2 sin GR;<br>• API005253: imputación histórica de V100131;<br>• API005261: 62800000 OB-1100-2512.05 S10;<br>• API005628: 62200000 CC-1200-TALLER, análogo a los NEW_VENDOR de dev.<br>Queda **API005629** sin líneas: avería de una barredora facturada a 1100, proveedor no dado de alta y objeto de coste no determinable con evidencia. El diff contra `snapshot_iter2` confirma que solo cambian `lines` de documentos no contabilizados. |

## Métricas de calibración del estimador de periodificaciones

### 1. Predicción del importe de la siguiente factura (por suministro, hasta 12 puntos por serie, ±15 %)
Columnas: tasa de acierto de cada método sobre todas las series y aciertos para cada proveedor de luz.

| método | todas las series | V100028 (n=105) | V100029 (n=96) |
|---|---|---|---|
| última | 351/581 | **75** | **66** |
| media 2 | 344/581 | 61 | 59 |
| media 3 | 360/581 | 63 | 53 |
| media 6 | 347/581 | 55 | 48 |
| mediana 3 | 342/581 | 56 | 51 |
| mediana 6 | 342/581 | 55 | 47 |
| media 12 | 363/581 | 60 | 53 |

En la luz, «última» gana a «media 3» por +12 y +13. El patrón estacional («mismo ciclo de hace un año») empata con «última» (26/37 y 32/49 frente a 25/37 y 30/49). En el resto de proveedores ningún método gana de forma robusta: V100030 y V100026 con media 6 ganan +3/48 y +2/24, pero solo mejoran 1 de 7 cierres a nivel de clave.

### 2. Backtest a nivel de clave del score (sociedad, proveedor) contra la verdad del organizador (±15 %)

| cierre | media 3 | **híbrido (luz = última)** | híbrido + media 6 en V100030/26 |
|---|---|---|---|
| 2026-08-31 | 34/45 | **35/45** | 35/45 |
| 2026-07-31 | 37/45 | **37/45** | 37/45 |
| 2026-06-30 | 28/43 | **30/43** | 30/43 |
| 2026-05-31 | 31/45 | **32/45** | 32/45 |
| 2026-04-30 | 30/43 | **32/43** | 32/43 |
| 2026-03-31 | 29/45 | **30/45** | 30/45 |
| 2026-02-28 | 29/46 | **30/46** | 32/46 |

El híbrido nunca empeora y mejora 6 de 7 cierres (+8 claves en total). Se adopta. La variante con media 6 no es robusta y se descarta.

### 3. Fracciones verificadas contra el organizador
* Luz: ciclo en curso 0,5 en todos los meses; ciclo anterior no recibido 1,0.
* Agua: septiembre **30/61 = 0,492** (el organizador usa 0,492 en 2025-09 y 2025-11).
* Mensuales: 1,0.

### 4. Cambios de importe por clave (iteración 2 → 3)

| clave | iteración 2 | iteración 3 |
|---|---|---|
| 1000/V100029 | 153.862 | 158.698 |
| 1100/V100028 | 602.595 | 641.456 |
| 1100/V100029 | 981.108 | 989.884 |
| 1200/V100028 | 119.991 | 139.372 |
| 1300/V100029 | 37.072 | 41.005 |
| 1910/V100028 | 66.932 | 70.082 |

El resto de claves no cambia.

## Pasada final de calidad
* AP sin regresiones: el diff sin `lines` contra el snapshot es nulo. Ninguna GR se usa dos veces y ninguna GR/IR supera su partida abierta.
* Cierre: la fracción del agua (30/61), los PREPAID (fórmula floor), el deterioro truncado y la valoración FX coinciden con la mecánica histórica del organizador. No hay WIP (todo CONFORME) ni concursos nuevos.
* Intragrupo, bancos y cobros: sin cambios; el evaluador los verificó línea a línea.

## Validaciones finales
* `make_je`: los 434 asientos, sin errores. Ids de asiento únicos, sin choque con el diario del ERP; en close, `je` = `journal_entry.id`.
* Cobertura de tasks: 100 % (297 / 25 / 34 / 12).
* `score.py phase_test phase_test phase_test/golden`: **100,00**.
* `trial_balance_recorded` = Σ diario (0 céntimos; 251 filas).
* `trial_balance_truth` = recorded + todos los asientos (0 céntimos; 257 filas); cada sociedad suma 0.
* `summary.json`: 297 / 25 / 34 / 12 / 4 / 83; tagged IC 2, AP 231, BANK 58, AR_BILL 25, AR_CASH 34, CLOSE 83.

## Incertidumbre residual (irreducible)
* Importes de las periodificaciones de octubre, desconocidos: se esperan ~70–75 % de las claves dentro del ±15 %.
* Qué par marca el organizador como tránsito intragrupo.
* BOOK_AMOUNT_ERROR registrado tanto en la casación como en `unmatched_book`.
