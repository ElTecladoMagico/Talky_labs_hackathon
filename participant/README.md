# Cierre contable de Grupo Kalmora (hackathon)

Sois el equipo de **contabilidad con IA** de **Grupo Kalmora**, un grupo de infraestructuras y servicios del tamaño de una empresa del IBEX 35. Tenéis que cerrar un mes como lo haría su centro de servicios compartidos. Hay tres frentes:

- **AP (cuentas a pagar):** la bandeja de proveedores.
- **AR (cuentas a cobrar):** facturar el mes y aplicar los cobros.
- **Conciliaciones:** bancos e intragrupo.

Al final se hace el **cierre**.

> **Todo es sintético.** Kalmora, sus sociedades, proveedores, clientes, NIF e IBAN son inventados. Los NIF españoles llevan el dígito de control incorrecto a propósito. Los tipos de cambio son una serie sintética («SYN-BCE»). La fiscalidad es realista pero ilustrativa.

## El grupo

| Sociedad | Nombre | País | Moneda | Qué hace |
|---|---|---|---|---|
| 1000 | Kalmora Infraestructuras y Servicios, S.A. | ES | EUR | Holding: cabecera del cash pooling, servicios corporativos, préstamo sindicado |
| 1100 | Kalmora Construcción, S.A.U. | ES | EUR | Obras públicas y privadas, subcontratas con ISP, factoring, confirming |
| 1200 | Kalmora Servicios Urbanos, S.L.U. | ES | EUR | Limpieza viaria, residuos, jardines; contratos municipales y recibos SEPA |
| 1300 | Kalmora Energía Renovable, S.L.U. | ES | EUR | 3 plantas solares: PPA y venta en mercado mediante representante |
| 1910 | UTE Kalmora Construcción – Hidrocon (Línea 9) | ES | EUR | Unión temporal al 50 % con un socio externo |
| 2100 | Kalmora Portugal – Construção e Serviços, Lda. | PT | EUR | Obras en Portugal (IVA 23 %/6 %, autoliquidação) |
| 3100 | Kalmora México Infraestructura, S.A. de C.V. | MX | MXN | Obra pública con anticipo, CFDI 4.0, préstamo intragrupo en EUR |

El plan de cuentas es único para el grupo y está basado en el PGC (`erp/chart_of_accounts.jsonl`). Todos los importes van en **céntimos enteros**. Las cantidades van en **milésimas** (`quantity_milli`).

## Fases

| Fase | Mes a cerrar | Datos | Para qué |
|---|---|---|---|
| `phase_dev` | **julio 2026** | Histórico hasta el 30/06 + el mes de julio, y **con golden** (`phase_dev/golden/`) | Desarrollar e iterar con `score.py` |
| `phase_test` | **septiembre 2026** | Histórico hasta el 31/08 + el mes de septiembre, **sin golden** | Evaluación final: se entrega una vez |

Cada fase es una foto del ERP **tal como estaba contabilizado** al cierre del mes, sin vuestro trabajo. En ella:

- Las facturas del mes están en la bandeja y no están contabilizadas.
- Los cobros entraron automáticamente desde el N43 a la cuenta `55500000` (pendientes de aplicar).
- Tesorería no ha registrado las comisiones del banco.
- Faltan las periodificaciones de cierre.
- Hay errores humanos que debéis encontrar.

## Qué hay en cada fase

```
phase_x/
├── erp/                         ← ERP a fecha de cierre (solo lo registrado)
│   ├── companies.json  chart_of_accounts.jsonl  tax_codes.json  cost_centers.jsonl  projects.jsonl (con PEP)
│   ├── vendors.jsonl  contractor_certificates.jsonl  customers.jsonl  sales_contracts.jsonl
│   ├── purchase_orders.jsonl  goods_receipts.jsonl (entradas y hojas de servicio)
│   ├── journal_entries.jsonl    ← libro diario completo desde 01/10/2024
│   ├── open_items.jsonl         ← partidas abiertas por socio y asignación
│   ├── ap_invoices.jsonl  ap_document_log.jsonl (qué se hizo con cada documento recibido antes)
│   ├── ar_invoices.jsonl  billing_history.jsonl  promissory_notes.jsonl  factoring_assignments.jsonl
│   ├── sepa_remittances.jsonl  penalty_notices.jsonl  intercompany_agreements.json  fx_rates.jsonl  bank_accounts.jsonl
├── inbox/
│   ├── ap/<doc_id>/             ← cada documento recibido en el mes: message.json + PDF / Facturae XML / CFDI XML / DUA
│   └── ar/billing/<item>/       ← certificaciones de obra, partes de servicio, decretos de revisión, producción PPA, liquidación de mercado
│       ar/remittances/          ← avisos de pago de clientes y exportaciones del portal FACe
│       ar/notices/              ← penalidades notificadas en el mes
├── bank/<cuenta>/<YYYY-MM>.n43 | .camt053.xml | .csv   ← extractos de los 4 últimos meses
│                 <YYYY-MM>.lines.jsonl                 ← mismo extracto con el identificador de cada línea (bank_line)
└── tasks/                       ← lista exacta de lo que hay que resolver
```

## Las seis tareas

| # | Tarea | Qué entregar | Peso |
|---|---|---|---|
| 1 | **AP – bandeja de proveedores** (`tasks/ap_documents.json`) | Por documento: tipo, decisión, motivo, sociedad, proveedor, importes, imputación por línea, pedido/posición y **asiento** | 30 % |
| 2 | **AR – facturación del mes** (`tasks/ar_billing_items.json`) | Por partida: facturar o no; y si se factura, importes, impuestos, retenciones, códigos DIR3 y **asiento** | 10 % |
| 3 | **AR – aplicación de cobros** (`tasks/ar_receipts.json`) | Por línea de abono del extracto: cliente, facturas o pagarés aplicados, diferencias y **asiento** desde `55500000` | 15 % |
| 4 | **Conciliación bancaria** (`tasks/bank_accounts.json`, 12 cuentas) | Casación banco↔libro, partidas sin casar clasificadas y **asientos de ajuste** | 20 % |
| 5 | **Conciliación intragrupo** (`tasks/intercompany.json`) | Diferencias por pareja de sociedades, causa y **asiento** corrector | 5 % |
| 6 | **Cierre** (`tasks/close.json`) | Periodificaciones, gastos anticipados, obra pendiente de certificar, valoración en divisa y deterioro de clientes | 10 % |
| ★ | **Balance de sumas y saldos** | Se calcula solo: el diario registrado más **todos** vuestros asientos, comparado con el balance correcto | 10 % |

Las reglas para decidir están en **[POLITICAS_CONTABLES.md](POLITICAS_CONTABLES.md)**. El formato de entrega está en **[FORMATO_ENTREGA.md](FORMATO_ENTREGA.md)**.

## Cómo se mide

```bash
python score.py phase_dev phase_dev mi_entrega_dev/      # en dev podéis autoevaluaros (usa phase_dev/golden)
```

- **AP:** F1 macro de la decisión, cabecera, imputación ponderada por importe, casación con pedido, asiento línea a línea (±2 céntimos), motivos y pagos.
- **AR:** exactitud por factura y por cobro: conjunto exacto de facturas e importes.
- **Bancos:** F1 de la casación, F1 y categoría de las partidas sin casar, ajustes.
- **Intragrupo:** detección de la causa y ajuste.
- **Cierre:** F1 de las partidas. Las periodificaciones de servicios se estiman con una tolerancia del ±15 %; el resto debe ser exacto.
- **Balance:** `1 − |diferencia| / |diferencia sin hacer nada|`.

Entregar algo parcial es válido: cada fichero puntúa por separado.

## Consejos

- El histórico (`journal_entries`, `ap_invoices`, `ap_document_log`, `billing_history`) enseña cómo contabiliza el grupo: cuentas, centros de coste, PEP y socios. Usadlo para aprender las imputaciones.
- No todo lo que entra en la bandeja es una factura. No todo lo que parece duplicado lo es: hay alquileres con el mismo importe todos los meses.
- Un IBAN distinto del de la ficha **sin** carta de cambio verificada es una alerta.
- Las facturas de obra de subcontratas llevan ISP y retención de garantía. Mirad bien «a origen» frente a «esta certificación».
- Banco, cobros e intragrupo están conectados: un barrido de pooling sin registrar descuadra el banco **y** la relación con la holding.
