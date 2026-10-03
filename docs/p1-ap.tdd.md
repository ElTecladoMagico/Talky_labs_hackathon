# P1 — evidencia de extracción, motor AP y correcciones de validación

Estado actual: motor general AP implementado; consultar la sección final de correcciones para resultados y límites vigentes. Las secciones anteriores conservan la evidencia histórica de cada hito.
Plan fuente: plan P1 acordado en el chat, derivado del texto del equipo aportado por el usuario.
No se usa golden como entrada del parser ni como caché de respuestas.

## Garantías y evidencia

| Garantía | Pruebas / ejecución | Resultado real |
|---|---|---|
| Céntimos con Decimal y fechas ISO; español, portugués e inglés | tests/test_ap_extract.py | PASS |
| XML Facturae/CFDI y tablas PDF, incluido signo de abonos | tests/test_ap_extract.py | PASS |
| Escaneos dev por OCR local; fallo OCR explícito y aislado | tests/test_ap_extract.py | PASS |
| Reutilización por hash de adjuntos/metadata y versión del parser | tests/test_ap_extract.py | PASS |
| Identidades pendientes se actualizan; decisiones finales se conservan | tests/test_ap_extract.py | PASS |
| Adjuntos no pueden escapar de su carpeta | tests/test_ap_extract.py | PASS |
| Cada documento solicitado tiene fila compartida, sin decisión ni asiento | fases completas dev/test sobre SQLite temporal | 305 / 297 filas; PASS |
| Infraestructura compartida no regresa | tests/test_infra.py | 19 PASS |

Comando de validación ejecutado:

```sh
.venv/bin/python -m pytest -q -p no:cacheprovider --cov=tasks.ap_extract --cov-report=term-missing --cov-report=xml:/private/tmp/p1-ap-final-coverage.xml
```

Resultado: **52 passed in 26.78s**, cobertura de líneas **92 %** (250 sentencias, 20 sin ejecutar).
No se ha medido cobertura de ramas. No hay interfaz web: E2E se valida con el CLI de extracción y las fases completas, no con Playwright.

Ejecución real del CLI:

```sh
.venv/bin/python -m tasks.ap_extract dev --rebuild
.venv/bin/python -m tasks.ap_extract test --rebuild
```

Dev: 305 documentos, 1 aviso. Test: 297 documentos, 4 avisos.
Comprobación SQLite posterior: 305/297 filas ap_result, 0 decisiones finales, 0 proposed_je en ambas bases.

## Checkpoints TDD en codex/p1-ap

| Ciclo | RED comprobado | GREEN comprobado |
|---|---|---|
| Extracción inicial | cb8385b: 19 fallos por parser inexistente | f2cb1ed: 19 PASS |
| Internacional / OCR | 132c83c: 3 fallos, 21 PASS | 55a189c: 24 PASS |
| Caché | 40979e0: 2 fallos, 25 PASS | 413549c: 27 PASS |
| Tablas OCR / renovación de pendientes | 548c7ff: 4 fallos, 26 PASS | 69a4a40: 30 PASS |
| Abono CFDI / evidencias separadas | 1857af8: 2 fallos, 31 PASS | 8ff98d0: 52 PASS y 92 % |

Verificada la rama actual y la ascendencia de los checkpoints inicial y último RED desde HEAD. No se han reescrito commits ni incluido el cambio ajeno preparado en .gitignore.

## Avisos y siguientes garantías necesarias

- Dev API005228: los totales XML/PDF difieren. Conservar ambas representaciones; decidir según §2.2.
- Test API005262: discrepancia XML/PDF.
- Test API005236, API005241 y API005242: OCR con filas desordenadas/unidad mal reconocida; suma de líneas distinta de base. Revisar la extracción antes de asentar. No inferir una corrección solo para forzar el cuadre.
- OCR depende de macOS, Vision y del binario compilado. Sin él, el escaneo queda marcado OCR_REQUIRED. La primera inicialización de Vision fue lenta; compilación única y llamadas posteriores verificadas.
- Las regex cubren las plantillas observadas. «Sin avisos» significa comprobaciones de extracción superadas, no factura contablemente válida. OCR todavía puede confundir caracteres de IBAN o descripciones: conservar fuentes y revisar antes de decidir o pagar.
- Falta completar periodos, retenciones compuestas, anticipos, referencias y metadatos efectivos de avisos de pago; resolver pedidos/entradas y objetos de coste.
- Falta tasks/ap.py: prioridad de decisiones, certificados/fraude, asientos/FX y evaluación dev del módulo AP. No se ha calculado puntuación AP ni generado una entrega final.

## Revisión Ponytail antes de los pasos 1 y 2

Se reutilizan SQLite y la biblioteca estándar: SQL con columnas/parámetros nombrados, UPSERT sin borrar anotaciones, diccionarios por NIF normalizado y `deepcopy` para aislar la caché. No se añaden dependencias, tablas, módulos provisionales ni reglas contables. El parser y su versión no cambian.

Garantías adicionales: prefijos NIF en minúsculas/espacios; identificadores ausentes o desconocidos no se adivinan; se conserva la primera coincidencia del maestro; no se altera `conn.row_factory`; una columna opcional no desplaza valores; una reextracción no elimina anotaciones ni decisiones finales; modificar una copia no modifica la caché original.

- RED `982bd24`: 2 fallos, 34 PASS; ejecución focalizada posterior: 2 fallos, 2 PASS.
- GREEN `3bc9121`: 36 pruebas AP PASS.
- Refactor `0cab943`: suite completa **55 PASS en 26.14s**; cobertura conjunta líneas/ramas **91.34 %**, umbral 80 % superado.

Comando ejecutado:

```sh
PYTHONDONTWRITEBYTECODE=1 COVERAGE_FILE=/private/tmp/p1-ponytail.coverage .venv/bin/python -m pytest -q -p no:cacheprovider --cov=tasks.ap_extract --cov-branch --cov-fail-under=80 --cov-report=term-missing
```

Además, reconstrucción SQLite temporal de ambas fases, reextracción desde caché y comparación de cada diccionario con el original: **305 dev y 297 test sin cambios**. Se conservan los cinco avisos. No se han cambiado las bases de trabajo ni las cachés versionadas en esta revisión. Checkpoints RED/GREEN verificados como ancestros del HEAD actual.
Los pasos 1 y 2 siguen pendientes: esta revisión prepara el flujo, no resuelve los avisos ni completa datos contables.

## Contrato parcial AP/NETTING solicitado por P2/P3

`tasks/ap.py` integra `run(conn)` en el pipeline existente. Revalida las fuentes con el extractor, reutiliza `make_je`/`propose` y publica identidades y decisiones en `ap_result`. Ponytail limita la implementación al perfil `MARKET_REP_FEE`; no añade dependencias ni motores contables paralelos. Los demás perfiles siguen pendientes.

- RED inicial: 11 fallos por ausencia de `tasks.ap`; las pruebas quedaron versionadas en `4bd0073` (checkpoint guardado durante esta sesión).
- GREEN `68e0a4f`: 11 PASS, cobertura conjunta líneas/ramas del módulo AP 89.61 %. Una prueba de entrada insegura se aisló al documento original: modificar importe/moneda cambia legítimamente la clave de duplicado de otra presentación válida.
- RED de evidencia modificada `e253cbb`: 1 fallo, 11 pruebas excluidas; no se detectaba un asiento previo cuya fuente dejaba de ser válida.
- GREEN `42a98b2`: 1 PASS, 11 excluidas; el conflicto ahora obliga al llamante a abortar/rollback, sin eliminar asientos de otros propietarios.
- Regresión final: **67 PASS en 68.40 s**, cobertura conjunta AP/extractor **91.03 %**. La primera ejecución en sandbox produjo 5 fallos de OCR y 61 PASS; la repetición autorizada con acceso al OCR nativo pasó completa sin modificar el extractor.

Comando final:

```sh
PYTHONDONTWRITEBYTECODE=1 COVERAGE_FILE=/private/tmp/p1-netting-all.coverage .venv/bin/python -m pytest -q -p no:cacheprovider --cov=tasks.ap --cov=tasks.ap_extract --cov-branch --cov-fail-under=80 --cov-report=term-missing
```

Verificación del pipeline real en SQLite temporal dev: 2 filas AP, un asiento, ninguna diferencia entre entrega y `propose()`. Prueba de dependencia con consumidor simulado: `ar_cash` observa en `ledger` el abono a `41000000`, proveedor `V100173`, assignment `26012023`, 828850 céntimos. Test temporal: `API004774`, factura `26012027`, POST y un asiento, sin IDs/importes dev fijados en producción.

Publicación autorizada en la base de trabajo dev: `API004299` POST y `API005210` DUPLICATE de la primera, sin asiento propio. Se conservaron las filas `bank_explained` y los eventos de otros propietarios; quedan **303 documentos dev pendientes**. No se usa golden en ejecución. Los módulos P2/P3 no están en este checkout: **no se ha verificado aquí el score ar_cash 1.000 ni 32/32**; requieren integrar este cambio y repetir su ejecución.

## Motor general y correcciones de validación — 2026-10-03

Esta sección sustituye los estados pendientes de los hitos anteriores. El usuario autorizó completar el motor general y pidió corregir los casos comunicados por P2 usando golden como referencia. Ponytail conserva un único módulo AP, los helpers SQLite/asientos existentes y la biblioteca estándar; no se añaden dependencias. Golden solo interviene en pruebas y evaluación offline.

### Checkpoints y garantías

| Cambio | RED real | GREEN real |
|---|---|---|
| Motor general y publicación de todos los documentos | `e7ca280`: 17 fallos, 4 PASS | `d24ac25`: 21 PASS, cobertura AP 89,94 % |
| Garantía, referencia rectificativa y solicitud de anticipo | `80de2ce`: 3 fallos | `9224702`: 3 PASS |
| Entradas y copias alteradas | `91d2e98`: 5 fallos | `941d2a8`: 5 PASS |
| Separar CUPS de IBAN y extraer periodos | `d83c59d`: 3 fallos | `a5a2a7c`: 3 PASS |
| Compras sin pedido, factor e invoice_date ausente | `077f1b3`: 4 fallos | `b176cc4`: 4 PASS |
| Tres facturas de energía, destinatario y total aritmético | `3b79772`: 5 fallos, 2 guardas PASS | `f33b062`: 7 PASS, 29 excluidas |

Los checkpoints de estas correcciones se verificaron como ancestros de HEAD en `codex/p1-ap`. La regresión previa al último ciclo fue 91 PASS y 91,19 % de cobertura conjunta AP/extractor. El extractor y sus cachés no cambian en el último ciclo.

Comando de la regresión final del motor y la infraestructura:

```sh
PYTHONDONTWRITEBYTECODE=1 COVERAGE_FILE=/private/tmp/p1-validation-feedback.coverage .venv/bin/python -m pytest tests/test_ap.py tests/test_infra.py -q -p no:cacheprovider --cov=tasks.ap --cov-branch --cov-fail-under=80 --cov-report=term-missing --cov-report=json:/private/tmp/p1-validation-feedback-coverage.json
```

Resultado: **55 PASS en 143,10 s**; cobertura AP conjunta **90,99 %**, líneas **93,09 %**, ramas **87,26 %**. No hay pruebas omitidas en esta ejecución. Se verifica que filas no contabilizadas carecen de asiento, la repetición es idempotente y los conflictos se detectan; los tests conservan sentinelas de P2/P3.

Las pruebas `test_energy_recurring_cost_matches_golden` comparan todas las líneas contables (sociedad, cuenta, importe, socio y objeto de coste) con golden para `API004338/F2631650`, `API004373/F2631651` y `API004445/F2631668`. Las tres pasan a POST. La inferencia compara dos ciclos históricos mensuales completos con el mismo orden de objetos de coste y exige un ciclo actual completo. Se registra método, meses y posición en `cost_evidence`; con ciclo incompleto sigue HOLD. Es una inferencia del histórico, no una relación explícita CUPS–obra: un cambio del orden de suministros requiere el maestro correspondiente.

La prueba del mandato N43 exige acuerdo con la sociedad de la cuenta bancaria, además de proveedor, número de factura, moneda e importe. `API005227` pasa a REJECT/WRONG_ADDRESSEE, `company=1100`, `source_company=1910`, sin asiento. Una contradicción entre mandato y maestro bancario no modifica la sociedad. Los complementos N43 contienen la referencia que falta en `.lines.jsonl`.

Los cuatro reenvíos `API005197/5200/5206/5210` quedan DUPLICATE, sin asiento y con los números canónicos publicados. `API005221` conserva REJECT/ARITHMETIC_ERROR y publica `gross=payable=264496`; mantiene `308802` en `source_amounts` y la representación PDF. No tiene XML. La base compartida anterior solo tenía dos decisiones; las correcciones de código necesitaban regenerar la entrega y `ap_result`.

### Evaluación y publicación

Ejecución aislada en SQLite nuevo para cada fase: **305/305 dev y 297/297 test** con decisión, todos los asientos cuadrados y ninguna diferencia entre la entrega y `propose()`. Score AP dev con `participant.score.score_ap(golden, salida)`:

- AP: **0,917723 → 0,939480**.
- F1 HOLD: **0,706 → 0,818**; macro F1 de decisiones: **0,946003**.
- Dev: 236 POST, 25 HOLD, 18 REJECT, 14 DUPLICATE, 12 NOT_INVOICE.
- Test: 220 POST, 3 POST_PAYMENT_BLOCK, 27 HOLD, 19 REJECT, 13 DUPLICATE, 15 NOT_INVOICE. No hay golden de test disponible para puntuar esa fase.

La publicación local actualiza `db/kalmora_dev.db`, `db/kalmora_test.db` y únicamente `submission/<fase>/ap.jsonl`. Se regeneran los eventos derivados `owner='P1', task='ap'` dentro de una transacción; la segunda ejecución debe devolver las mismas filas, y las filas bancarias/eventos de otros propietarios deben permanecer idénticos. Copias previas: `/private/tmp/p1-ap-before-dev-20261003.db` y `/private/tmp/p1-ap-before-test-20261003.db`. Son archivos locales ignorados por Git. El código y las pruebas están versionados; P2/P3 deben ejecutar la versión actual para regenerar sus propias bases.

### Límites pendientes

Quedan **9 diferencias de decisión** en dev frente a golden: `API004130`, `API004307`, `API004204`, `API004314`, `API004095`, `API004559`, `API004123`, `API005230` y `API005205`. Los siete primeros requieren completar evidencia de pedidos/imputación; los dos últimos, fraude/representaciones duplicadas. En API005205 el documento escaneado y el original presentan importes distintos: sigue siendo un caso pendiente de doble contabilización, que debe resolverse antes de considerar AP completo.

Persisten cinco avisos de extracción entre ambas fases. Tampoco se ha completado la aplicación de anticipos al cambio histórico. Las copias idénticas con recepción cronológicamente contradictoria usan un representante estable y señalan `RECEIPT_ORDER_CONFLICT` (`API005197`, `API005203`); no se presenta esa selección como prueba de primera recepción real.

No se ha ejecutado el motor real de P2/P3, ausente de este checkout. Los tres recibos de energía y NETTING_AP están preparados en AP/ledger; **no se afirma bank_rec=1,000 ni ar_cash=1,000** hasta repetir la integración del equipo.

## Recuperación mínima de pedidos desde main — 2026-10-03

Este apartado sustituye los resultados y límites anteriores para la rama `codex/p1-ap-po-fix`. Fuente: feedback del equipo y políticas contables; no se ha usado golden como entrada del motor.

### Reproducción y checkpoints

Se actualizó el main local por avance rápido desde `origin/main`. En `main=c3eee7f`, antes de crear la rama, el pipeline real sobre una base temporal reprodujo las nueve diferencias AP, AP 0,9395, TOTAL 96,00 y siete partidas FX_REVAL (sin API004559). Banco y ar_cash ya dieron 1,000. Base y salida inicial: `/var/folders/gj/0k1mzmmx5blffmmsrg4j63rh0000gq/T/p1-main-dev-wyg1wfau/`.

La rama se creó con `git switch -c codex/p1-ap-po-fix main`; su punto común con main es `c3eee7f0b2d45a8d75cd72449f15b67fbf13aeb3`. Main no recibió las correcciones.

- RED `d8ddb60`: cuatro fallos debidos al HOLD incorrecto y siete comprobaciones de seguridad correctas, antes de cambiar producción.
- GREEN `3197d02`: once comprobaciones correctas. La primera ejecución tras el arreglo detectó además una diferencia independiente del redondeo FX de P3 (67348 frente a 67344 céntimos). La prueba de integración se acotó al contrato AP: llegada de la partida, moneda original, proveedor, asignación y asiento cuadrado. No se presenta como igualdad exacta de la valoración FX con golden.

Comando focalizado, ejecutado en RED y GREEN:

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_ap.py -q -p no:cacheprovider -k 'source_backed_po_recovery or recovered_rental or direct_rental_requires or stale_po_recovery'
```

### Garantías verificadas

| Necesidad | Prueba en tests/test_ap.py | Resultado |
|---|---|---|
| Recuperar pedidos antiguos solo con entradas existentes y conservar la imputación | test_source_backed_po_recovery_matches_golden (API004307, API004314) | POST y asiento completo igual a golden |
| Reconocer el alquiler mensual contabilizado históricamente sin GR/IR | test_source_backed_po_recovery_matches_golden (API004559) | POST y asiento completo igual a golden |
| Publicar la partida USD para el cierre de P3 | test_recovered_rental_is_available_to_p3_fx_without_p3_changes | Partida FX presente con proveedor y asignación correctos |
| No aceptar alquiler sin dos precedentes, con antecedentes GR/IR o con importe distinto | test_direct_rental_requires_repeated_matching_expense_history | HOLD, sin asiento |
| No omitir entrada, sociedad ni moneda al recuperar un pedido antiguo | test_stale_po_recovery_keeps_receipt_and_identity_checks | HOLD o REJECT, sin asiento |

La misma recuperación se usa desde `_coding`, incluida su llamada recursiva para abonos. `po_evidence` registra el pedido declarado, el resuelto y las entradas, o los dos documentos históricos del alquiler. Simplificación Ponytail: sin dependencias nuevas ni excepciones por doc_id; el alquiler exige un único concepto mensual, precio exacto y antecedentes directos inequívocos. Un contrato con requisitos de recepción distintos necesitará evidencia explícita; no se amplía la excepción a compras de materiales.

### Regresión, cobertura e integración

```sh
PYTHONDONTWRITEBYTECODE=1 COVERAGE_FILE=/private/tmp/p1-po-fix.coverage .venv/bin/python -m pytest -q -p no:cacheprovider --cov=tasks.ap --cov-branch --cov-fail-under=80 --cov-report=term-missing --cov-report=json:/private/tmp/p1-po-fix-coverage.json
```

Resultado: **172 PASS en 221,71 s**, sin pruebas omitidas. Cobertura AP conjunta **91,30 %**. Pipeline completo con los módulos reales P1/P2/P3, sin revisión IA ni llamadas externas, usando `/private/tmp/p1-main-regression.py dev` y `test` con bases nuevas:

- Dev: AP **0,9501**, F1 HOLD **0,878**, cierre **0,8062**, balance **0,9900**, TOTAL **96,47**. Banco, ar_cash, ar_billing e intragrupo **1,000**; sus salidas son idénticas byte a byte a main. Solo cambian tres filas AP: API004307, API004314 y API004559.
- P3 genera ocho partidas FX_REVAL, incluida AP:API004559. Su importe sigue cuatro céntimos por encima de golden por la inversión del tipo USD redondeada a seis decimales en `tasks.close.fx_rate`; P1 no modifica esa función.
- Test: 297 decisiones; 222 POST, 3 POST_PAYMENT_BLOCK, 25 HOLD, 19 REJECT, 13 DUPLICATE y 15 NOT_INVOICE. API005024 y API004695 pasan de HOLD a POST respecto a la publicación AP anterior. No hay golden de test para verificar exactitud.
- Ambas fases: ninguna decisión nula, todos los eventos cuadrados y `run.inconsistencies` vacío.

Salidas temporales: dev `/var/folders/gj/0k1mzmmx5blffmmsrg4j63rh0000gq/T/p1-main-dev-1oz3m9as/`; test `/var/folders/gj/0k1mzmmx5blffmmsrg4j63rh0000gq/T/p1-main-test-a38342ul/`. No se han sustituido `db/kalmora_*.db` ni `submission/` compartidos.

### Límites restantes

Seis diferencias de decisión dev: API004095 y API004123 (hojas de servicio ambiguas), API004130 (PEP sin evidencia), API004204 (entrada 5000037485 citada por golden ausente del ERP), API005230 (fraude esperado sin evidencia bancaria en las fuentes) y API005205 (representación escaneada con importe distinto; aún POST, riesgo de doble contabilización pendiente). No se fuerza ninguno desde golden. Persisten los avisos de extracción, la aplicación de anticipos al cambio histórico y el conflicto de cronología documentados antes. La diferencia de cuatro céntimos de P3 debe resolverse antes de afirmar FX_REVAL exacto.

### Última revisión para el PR a main

Se integró `origin/main=7758693beba65782bbff661331c60dda83c5b4fe` (PR de utilidades compartidas) sin reescribir los checkpoints TDD. El único conflicto era aditivo en `tests/test_ap.py`: se conservaron las pruebas de ambas ramas. El diff final contra ese main queda limitado a README, esta evidencia, `tasks/ap.py` y `tests/test_ap.py`; las utilidades compartidas siguen siendo las de main.

Se ejecutó el código AP del main actual en una base nueva con los tres documentos: **API004307, API004314 y API004559 siguen HOLD/QTY_NOT_RECEIVED en main**. Comando: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python /private/tmp/p1-pr-main-proof.py`.

Regresión final: **179 PASS en 231,31 s**, sin pruebas omitidas, cobertura AP **91,82 %**:

```sh
PYTHONDONTWRITEBYTECODE=1 COVERAGE_FILE=/private/tmp/p1-pr-final.coverage .venv/bin/python -m pytest -q -p no:cacheprovider --cov=tasks.ap --cov-branch --cov-fail-under=80 --cov-report=term-missing --cov-report=json:/private/tmp/p1-pr-final-coverage.json
```

Los pipelines dev y test también se repitieron tras integrar main: AP **0,9501**, TOTAL **96,47**, banco/cobros/facturación/intragrupo **1,000** en dev; entrega y `propose()` siguen coincidiendo en ambas fases. Salidas aisladas: dev `/var/folders/gj/0k1mzmmx5blffmmsrg4j63rh0000gq/T/p1-main-dev-7onff73e/`; test `/var/folders/gj/0k1mzmmx5blffmmsrg4j63rh0000gq/T/p1-main-test-jrzd8a12/`. La revisión no añade excepciones por documento ni nuevas dependencias; no sustituye las bases compartidas. Los seis casos pendientes y los cuatro céntimos FX anteriores siguen fuera del arreglo.
