# P1 — hito 1: extracción e identidades pendientes

Estado: extracción implementada; decisiones contables y asientos AP todavía NO implementados.
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
