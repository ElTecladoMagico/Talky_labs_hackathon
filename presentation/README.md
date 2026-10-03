# Kalmora · presentación de cinco minutos

Web estática de siete diapositivas en español, con P1, P2 y P3. No ejecuta el ERP ni actualiza las cifras: muestra la validación documentada del 03/10/2026 en la revisión `8efa1d4`.

## Abrir y presentar

Abrir `dist/index.html` directamente en el navegador: funciona sin internet, sin instalación y sin servidor. También puede servirse desde la raíz del proyecto:

```sh
python3 -m http.server 8765 --bind 127.0.0.1 --directory presentation/dist
```

Abrir `http://127.0.0.1:8765/`. Avanzar con los botones, el menú lateral, flechas o PageUp/PageDown. Home/End van al principio/final. `N` muestra el guion; está oculto inicialmente. El temporizador empieza solo al pulsar Iniciar; permite pausar y reiniciar, y se detiene a los cinco minutos. Pantalla completa usa la función nativa del navegador; si no está disponible, usar el menú del navegador.

El guion se muestra en la misma ventana: ocultarlo al proyectar si no se quiere que lo vea la audiencia. Para imprimir o guardar en PDF, utilizar la impresión del navegador: incluye las siete diapositivas, no solo la activa, sin controles ni guion.

## Recorrido

| Diapositiva | Mensaje | Tiempo |
|---|---|---|
| 1. El reto | Documentos dispersos; cierre con evidencia | 35 s |
| 2. Un solo sistema | Orden de tareas y libro compartido | 40 s |
| 3. P1 | Extraer, contrastar y decidir sobre proveedores | 45 s |
| 4. P2 | Conciliar bancos y operaciones intragrupo | 50 s |
| 5. P3 | Facturar, aplicar cobros y ajustar el cierre | 55 s |
| 6. Caso conectado | Cobro de energía menos honorarios | 40 s |
| 7. Resultados | Score dev y límites pendientes | 35 s |
| **Total** | | **300 s** |

Tiempos orientativos para ensayar; no hay avance automático ni garantía sobre la duración de la lectura.

## Fuentes y alcance

- README del equipo y `docs/p1-ap.tdd.md`: resultados del pipeline de desarrollo (96,47/100, 179 tests; AP 0,9501, cierre 0,8062, balance 0,9900; resto 1,000). Son scores del evaluador, no tasas de facturas correctas.
- `run.py`: orden real `ap → ar_billing → bank_rec → ic → ar_cash → close`.
- `tasks/bank_rec.py` y `tasks/ic.py`: funciones de P2.
- `tasks/ar_billing.py`, `tasks/ar_cash.py` y `tasks/close.py`: funciones de P3.
- Caso `BL0000567` del golden dev: factura EN26-00014 de 438.854,31 €, honorario 26012023 de 8.288,50 €, banco 430.565,81 €. Golden es referencia de validación, no entrada del motor.
- `participant/README.md` y `FORMATO_ENTREGA.md`: seis JSONL, dev con golden y test sin golden.

No se publica el ERP, PDFs, bases SQLite, cachés de extracción ni credenciales. Solo la presentación y sus fuentes estáticas. Las cifras deben actualizarse manualmente cuando cambie la validación. Pendientes documentados: seis diferencias AP, 4 céntimos en FX y otros límites de extracción/anticipos. El análisis intragrupo actual prioriza la mayor factura en tránsito y avisa sobre el resto: no se presenta como cobertura universal.

## Pruebas

Con Node 24 o posterior, desde la raíz del proyecto:

```sh
node --test --experimental-test-coverage --test-coverage-include='presentation/dist/deck.js' --test-coverage-lines=80 --test-coverage-functions=80 --test-coverage-branches=80 presentation/tests/deck.test.cjs
```

Sin dependencias añadidas. En este equipo se ha utilizado el runtime Node ya incluido en VS Code (`ELECTRON_RUN_AS_NODE=1`). Evidencia: `docs/presentation.tdd.md`.
