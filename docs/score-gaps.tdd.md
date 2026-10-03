# Huecos frente al golden: AP (asientos) y cierre (periodificaciones)

Rama `fix/score-gaps`, desde `main` en `e407478`. Los huecos salen de comparar `submission/dev` con `phase_dev/golden`, documento a documento y partida a partida. Golden se usa solo para tests y evaluación, nunca al ejecutar.

## Resultado (dev, `run.py dev --rebuild`)

| | AP | Cierre | Balance | TOTAL |
|---|---|---|---|---|
| Antes (`main`) | 0.950 | 0.806 | 0.990 | 96.47 |
| Después | **0.969** | **0.872** | **0.999** | **97.78** |

En cada paso se ejecutó dev y test desde cero y se comprobó que solo cambian los ficheros esperados: `ap.jsonl` en los tres arreglos de AP y `close.jsonl` en el de cierre. Partida a partida, ningún asiento ni periodificación empeora frente a la salida anterior.

## Cambios (test en rojo → arreglo en verde)

| # | Qué se garantiza | Test | RED | GREEN | Efecto en dev |
|---|---|---|---|---|---|
| 1 | El IVA con inversión del sujeto pasivo lleva **una sola pareja 472/477** por factura (cuotas redondeadas por línea) | `test_ap.py::test_reverse_charge_*` | `a8112f5`, 2 fallos: una pareja por línea | `a81ef2b` | 29 facturas. AP 0.950 → 0.964 |
| 2 | En compras sin pedido, **cada línea usa la cuenta que el histórico del proveedor da a ese concepto**. El texto del diario está truncado, así que se compara por prefijo normalizado de al menos 12 caracteres. | `test_ap.py::test_non_po_line_account_follows_history_*` | `d7a9953`, 3 fallos de cuenta | `bfc8d28` | 12 asientos mejoran, 0 empeoran. Canon y suplidos van a 63100000 |
| 3 | El CFDI **no borra la retención de garantía** del PDF (3100) | `test_ap.py::test_cfdi_does_not_erase_*` | `b54e220`, 2 fallos: retención 0 | `1029666` | 5 asientos mejoran. Balance 0.992 → 0.999 |
| 4 | Periodificaciones: **la mediana usa solo tramos que llegan a fin de mes**. Lo periodificado hasta el cierre anterior **se arrastra** si su factura no llegó como POST (mismo id, o misma sociedad y proveedor facturado hasta ese día). Sin `ap_result` no se arrastra nada. | `test_p3_tasks.py::test_accrual_*`, `test_previous_month_end_*`, `test_one_off_*`, `test_without_ap_*` | `e94aa27`, 3 fallos | `ae7ed03` | 8 partidas mejoran, 0 empeoran. Cierre 0.806 → 0.872 |

Validación final: `python3 -m pytest -q --deselect tests/test_ap_extract.py` da **149 pasan**. Los tests de extracción no cambian; los 6 de OCR necesitan el binario local de P1.

## Decisiones y límites

- **Arreglo 3 hecho en `ap.py` y no en el extractor.** Subir `VERSION` en `ap_extract` obliga a reextraer los escaneos con el OCR local de P1. Está marcado `ponytail:` para moverlo en la próxima versión del extractor.
- **No se cambió la ventana de la mediana.** Se probaron ventanas de 1 a 5 y las diferencias eran de 1 partida sin patrón (ruido): ajustarla sería sobreajustar a dev.
- **Huecos que siguen:**
  - Servicios variables (viajes, mensajería), entre −29 % y +40 %: el golden usa el importe real de la factura futura.
  - Estacionalidad de la energía, alrededor de +17 % en V100029/1100.
  - 5 decisiones de AP distintas del golden (lista de P1).
- **Para P1 (test):** API005261 (V100034) se contabiliza en 1910 con el mismo neto (79.012) y periodo que lo periodificado en 1100. Puede ser un destinatario erróneo; conviene revisarlo.
