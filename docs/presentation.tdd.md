# Presentación web P1/P2/P3 — evidencia TDD

Plan derivado de la petición: explicar todo el proyecto en una web de cinco minutos, incluyendo P2 y P3. Rama independiente `codex/presentation-5min`, creada desde `8efa1d4`; no modifica el PR AP ni sus motores.

Ponytail: HTML, CSS y JavaScript estáticos, sin framework, dependencias, backend, acceso al ERP ni cálculo nuevo de métricas. Sites permite publicar una copia privada de la presentación. Las fuentes contables se han leído para preparar el contenido, no se suben al sitio.

## RED

`4475ff9`: pruebas ejecutadas antes de la implementación; fallo esperado `Cannot find module '../dist/deck.js'`. Runtime disponible Node 24.21.0 incluido en VS Code; detector ECC no encontró npm ni package.json. Se utilizó el test runner nativo sin instalar paquetes.

## GREEN

Comando desde la raíz:

```sh
ELECTRON_RUN_AS_NODE=1 '/Applications/Visual Studio Code.app/Contents/MacOS/Code' --test --experimental-test-coverage --test-coverage-include='presentation/dist/deck.js' --test-coverage-lines=80 --test-coverage-functions=80 --test-coverage-branches=80 presentation/tests/deck.test.cjs
```

Siete pruebas sin omitir. Garantías: hash inválido/fuera de rango; una diapositiva activa; navegación y límites; guion actual y ocultación; reloj sin deriva al pausar, reinicio y parada a 300 s; pantalla completa y errores; siete diapositivas/300 s, P2/P3, cifras y límites, referencias locales sin dependencias externas. Durante GREEN se hizo explícito el prefijo `#` para que navegación y fixture se comporten igual que un Location del navegador.

Resultado final: **7 PASS**, 0 omitidas, 98,95 ms. Cobertura del controlador: **98,80 % líneas, 96,43 % ramas y 94,12 % funciones**, superando los tres umbrales 80 %. `git diff --check` sin incidencias. La cobertura es del controlador JavaScript, no una comprobación visual de CSS o accesibilidad completa.

## Límites de verificación

Pruebas unitarias/integración del controlador con DOM mínimo y lectura real de HTML/assets. Previsualización local: HTTP 200 en `http://127.0.0.1:8765/`. No se ha podido hacer QA visual/E2E en navegador: Computer Use no dispone de navegador ni superficie nativa en este entorno (`iab` no disponible). No se afirma que Playwright, impresión o ajustes responsive hayan sido verificados en un navegador real. La publicación no depende de esa comprobación; se entrega el código estático utilizable sin alojamiento.

No se ha vuelto a ejecutar el pipeline contable: las métricas de la presentación proceden de la validación documentada en 8efa1d4. Esta tarea no cambia datos ni resultados P1/P2/P3.
