# Huecos frente al golden: AP (asientos) y cierre (periodificaciones)

Rama `fix/score-gaps`, desde `main` en `e407478`. Los huecos salen de comparar `submission/dev` con `phase_dev/golden`, documento a documento y partida a partida. Golden se usa solo para tests y evaluación, nunca al ejecutar.

## Resultado (dev, `run.py dev --rebuild`)

| | AP | Cierre | Balance | TOTAL |
|---|---|---|---|---|
| Antes (`main`) | 0.950 | 0.806 | 0.990 | 96.47 |
| Después | **0.969** | **0.856** | **0.999** | **97.62** |

En cada paso se ejecutó dev y test desde cero y se comprobó que solo cambian los ficheros esperados: `ap.jsonl` en los tres arreglos de AP y `close.jsonl` en el de cierre. Partida a partida, ningún asiento ni periodificación empeora frente a la salida anterior.

## Cambios (test en rojo → arreglo en verde)

| # | Qué se garantiza | Test | RED | GREEN | Efecto en dev |
|---|---|---|---|---|---|
| 1 | El IVA con inversión del sujeto pasivo lleva **una sola pareja 472/477** por factura (cuotas redondeadas por línea) | `test_ap.py::test_reverse_charge_*` | `a8112f5`, 2 fallos: una pareja por línea | `a81ef2b` | 29 facturas. AP 0.950 → 0.964 |
| 2 | En compras sin pedido, **cada línea usa la cuenta que el histórico del proveedor da a ese concepto**. El texto del diario está truncado, así que se compara por prefijo normalizado de al menos 12 caracteres. | `test_ap.py::test_non_po_line_account_follows_history_*` | `d7a9953`, 3 fallos de cuenta | `bfc8d28` | 12 asientos mejoran, 0 empeoran. Canon y suplidos van a 63100000 |
| 3 | El CFDI **no borra la retención de garantía** del PDF (3100) | `test_ap.py::test_cfdi_does_not_erase_*` | `b54e220`, 2 fallos: retención 0 | `1029666` | 5 asientos mejoran. Balance 0.992 → 0.999 |
| 4 | Periodificaciones: **la mediana usa solo tramos que llegan a fin de mes**. Los ciclos atrasados y los servicios puntuales no la inflan. | `test_p3_tasks.py::test_accrual_estimate_ignores_late_cycle_entries`, `test_one_off_service_is_not_carried_over` | `e94aa27` | `ae7ed03`; arrastre retirado después | Cierre 0.806 → 0.856 |

Validación final: `python3 -m pytest -q --deselect tests/test_ap_extract.py` da **146 pasan**. Los tests de extracción no cambian; los 6 de OCR necesitan el binario local de P1.

## ¿Generaliza fuera de julio de dev?

**Periodificaciones: backtest contra los cierres históricos.** Para cada mes pasado se toma como verdad lo que el generador periodificó ese mes (sus asientos `CLOSE_ACCRUAL`). Se borra de una copia de la base todo lo posterior al cierre anterior, se ejecutan la versión de `main` y la nueva, y se puntúa con la tolerancia del evaluador.

| Variante | F1 medio (abr, may, jun, jul, ago) | Peor caída mensual |
|---|---|---|
| `main` | 0,694 | — |
| Primera versión del arrastre (julio de dev = 0.872) | 0,580 | −0,29 |
| **Final: solo «mediana con tramos hasta fin de mes»** | **0,715** | **−0,026** |
| Arrastre solo de ciclos cerrados (retirado) | 0,724 | −0,011 |

La primera versión del arrastre **se sobreajustaba a julio**: en los meses pares contaba dos veces el agua bimestral, porque el tramo 01/05–30/06 ya incluye mayo. Una versión corregida (arrastrar solo ciclos cerrados) generalizaba, pero **se retiró**:
- salía de un único caso del golden (Fuenteclara 1200);
- aportaba solo +0,009 de F1 en el backtest (menos de una partida al mes) y +0,16 puntos en dev;
- añadía unas 20 líneas de expresiones regulares y lógica de cobertura.

**AP: coherencia en test**, comparando documento a documento la salida de `main` con la de esta rama:
- 32 facturas solo agrupan la pareja de IVA, con el mismo total y las mismas cuentas.
- 13 pasan una línea a 631, y todas son canon de saneamiento o de residuos.
- 7 recuperan la retención, todas subcontratas de 3100, con bruto − retención = líquido.
- Ningún otro cambio.

## Decisiones y límites

- **Arreglo 3 hecho en `ap.py` y no en el extractor.** Subir `VERSION` en `ap_extract` obliga a reextraer los escaneos con el OCR local de P1. Está marcado `ponytail:` para moverlo en la próxima versión del extractor.
- **No se cambió la ventana de la mediana.** Se probaron ventanas de 1 a 5 y las diferencias eran de 1 partida sin patrón (ruido): ajustarla sería sobreajustar a dev.
- **Huecos que siguen:**
  - Servicios variables (viajes, mensajería), entre −29 % y +40 %: el golden usa el importe real de la factura futura.
  - Estacionalidad de la energía, alrededor de +17 % en V100029/1100.
  - 5 decisiones de AP distintas del golden (lista de P1).
- **Para P1 (test):** API005261 (V100034) se contabiliza en 1910 con el mismo neto (79.012) y periodo que lo periodificado en 1100. Puede ser un destinatario erróneo; conviene revisarlo.
