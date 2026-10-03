# Manual de políticas contables de Grupo Kalmora (extracto para el cierre)

Este manual contiene las reglas con las que el grupo decide y contabiliza. Lo que no esté aquí se deduce del histórico: el diario y los documentos ya procesados muestran cómo se ha hecho siempre.

## 1. Convenciones generales

- **Importes:** en céntimos enteros y en la moneda local de la sociedad (EUR; MXN en 3100). Una línea en moneda extranjera se convierte al **tipo SYN-BCE de la fecha de la factura**, o al último publicado si ese día no hay. El redondeo se hace por línea y la diferencia la absorbe la línea del proveedor o del cliente.
- **Socio (`partner`):**
  - el id del proveedor en 400/410/403/407/40000900/40090000;
  - el id del cliente en 430/431/436/438/43000900/43090000/49000000;
  - el código de sociedad en las cuentas intragrupo 5520/5521/5522/2423/1633;
  - `FACTOR-BAE` en 55300000.
- **Objeto de coste:** las cuentas de gasto, ingreso e inmovilizado llevan centro de coste (`cost_center`) **o** elemento PEP (`wbs`), nunca los dos. En obra se imputa al PEP; en estructura y servicios, al centro de coste.
- **Cuentas de cada proveedor:** cada proveedor tiene su cuenta de acreedor (`reconciliation_account`: 40000000 para bienes y subcontratas, 41000000 para servicios, 40300000 para el grupo), su cuenta de gasto por defecto y su código de IVA por defecto. La ficha manda salvo que el documento o el pedido digan otra cosa.

## 2. Cuentas a pagar

### 2.1 Tipos de documento

| Tipo | Qué es | Decisión |
|---|---|---|
| `INVOICE` | Factura ordinaria (PDF, Facturae XML o CFDI) | Según 2.2 |
| `CREDIT_NOTE` | Factura rectificativa o abono | `POST`: asiento inverso imputado a la misma cuenta y objeto de coste |
| `DOWN_PAYMENT_REQUEST` | Solicitud de anticipo de proveedor extranjero con pedido aprobado | `POST`: Dr 40700000 / Cr 40000000 |
| `PROFORMA` | Proforma u oferta | `NOT_INVOICE`, acción `NONE` |
| `VENDOR_STATEMENT` | Extracto o recordatorio de deuda | `NOT_INVOICE`, acción `NONE` |
| `FACTORING_NOTICE` | Notificación de cesión de créditos | `NOT_INVOICE`, acción `REGISTER_ALTERNATIVE_PAYEE` |
| `TAX_GARNISHMENT_ORDER` | Diligencia de embargo de la AEAT | `NOT_INVOICE`, acción `REGISTER_EMBARGO` |
| `BANK_DETAILS_CHANGE` | Carta firmada de cambio de cuenta con certificado bancario | `NOT_INVOICE`, acción `UPDATE_BANK_DETAILS` |
| `CONTRACTOR_TAX_CERTIFICATE` | Certificado de estar al corriente (art. 43.1.f LGT) | `NOT_INVOICE`, acción `UPDATE_CONTRACTOR_CERTIFICATE` |

### 2.2 Decisión sobre una factura

Las comprobaciones se hacen en este orden. Gana la primera que falle.

1. **Duplicado** (`DUPLICATE`, `duplicate_of` = `doc_id` del primer documento): mismo proveedor y número de factura (normalizado: sin guiones, barras ni prefijos) e importe, ya recibido en el histórico o antes en el mes. Puede llegar como reenvío, escaneo, por otro canal o con el número escrito de otra forma. Dos alquileres del mismo importe en meses distintos **no** son duplicados.
2. **Rechazo** (`REJECT`): hay que pedir una factura nueva al proveedor.
   - `MANDATORY_FIELD_MISSING`: falta el NIF del destinatario.
   - `WRONG_ADDRESSEE`: va dirigida a otra sociedad del grupo (o a 1100 en vez de a la UTE 1910) distinta de la que hizo el pedido.
   - `ISP_NOT_APPLIED`: un subcontratista de obra repercute IVA cuando procede inversión del sujeto pasivo.
   - `VAT_RATE_INCORRECT`: tipo de IVA distinto del aplicable. Recogida y tratamiento de residuos, limpieza viaria y agua llevan 10 %; el resto, 21 %.
   - `WITHHOLDING_MISSING`: un profesional persona física o un arrendador urbano no practica la retención.
   - `ARITHMETIC_ERROR`: el total no es la base más las cuotas.
   - `CERTIFICATION_CUMULATIVE_BILLED`: la subcontrata factura el importe a origen en vez del de esta certificación.
   - `CFDI_MISMATCH`: el XML del CFDI no coincide con el PDF.
3. **Retención** (`HOLD`): no se contabiliza todavía.
   - `VENDOR_NOT_IN_MASTER`: el proveedor no está dado de alta.
   - `BANK_DETAILS_CHANGED`: el IBAN de la factura difiere del de la ficha y no lo respalda ni una carta de cambio firmada (registrada o recibida en el mes) ni una cesión de créditos a un factor; o el correo viene de un dominio parecido al habitual. Se trata como posible fraude.
   - `QTY_NOT_RECEIVED`: algún albarán facturado no tiene entrada de mercancía.
   - `PRICE_VARIANCE`: el precio unitario supera el del pedido en más del **2 %** o en más de **150 €** por línea.
4. **Contabilizar con bloqueo de pago** (`POST_PAYMENT_BLOCK`, `payment_block = CONTRACTOR_CERTIFICATE_EXPIRED`): el subcontratista de obra no tiene certificado del art. 43 vigente a la fecha de la factura.
5. **Contabilizar** (`POST`). Una diferencia de precio dentro de la tolerancia se imputa al mismo gasto u objeto de coste que la línea.

**Beneficiario del pago (`payee`):**

- Si hay cesión de créditos vigente a la fecha de la factura, el pago va al **factor**: `{"type":"FACTOR"}`.
- Si hay diligencia de embargo de la AEAT recibida antes que la factura, va a la AEAT: `{"type":"AEAT_EMBARGO"}`.
- En cualquier otro caso, `payee` es `null`.

### 2.3 Asiento de una factura de proveedor

- **Líneas con pedido y entrada:**
  - Dr 40090000 (cuenta puente GR/IR) por el **valor de las entradas** (cantidad × precio del pedido), con socio el proveedor.
  - La diferencia de precio, Dr a la cuenta de gasto de la línea con su objeto de coste.
- **Líneas sin pedido:** Dr a la cuenta de gasto o inmovilizado con su objeto de coste.
- **IVA:**
  - Soportado deducible: Dr 47200000.
  - ISP de obra (SISP), intracomunitario (SIC), servicios de no establecidos (SIS) y autoliquidação portuguesa (PAUT/PSIS): Dr 47210000 y Cr 47710000 por la cuota autorrepercutida.
  - IVA de importación del DUA, suplido por el transitario: Dr 47200000.
  - Exento o no sujeto (seguros, arrendamiento rústico, tasas, REAV): sin cuota.
- **Retenciones:**
  - IRPF y equivalentes: Cr 47510000. Tipos: IRPF 15 % profesional, 7 % nuevo profesional, 19 % arrendamiento urbano; en México ISR 10 %, IVA retenido 10,67 % y fletes 4 %; en Portugal IRS 25 %.
  - Retención de garantía de obra del 5 % sobre la base: Cr 40000900 con socio el proveedor.
- **Cuenta del proveedor:** Cr por el importe a pagar (total − retenciones − garantía − anticipos aplicados).
- **Anticipos:** se aplican al **tipo de cambio histórico** del anticipo: Cr 40700000.

## 3. Cuentas a cobrar

### 3.1 Facturación del mes

- **Certificaciones de obra:**
  - Se factura **solo** la certificación aprobada por la Dirección Facultativa, por el **importe de esta certificación** (a origen − anterior).
  - Fecha de la factura: último día del mes certificado. Vencimiento: fecha + días del contrato.
  - Si está pendiente de aprobación: `SKIP_PENDING_APPROVAL`, y en el cierre se registra la obra ejecutada pendiente de certificar (§5).
- **Impuestos y deducciones según el contrato (`tax`):**
  - R21: IVA 21 %.
  - RISP: obra de edificación para un promotor empresario; sin IVA y con la leyenda del art. 84.Uno.2º f.
  - R10: 10 %, para limpieza viaria y residuos.
  - PR06/PR23/PRAUT: Portugal.
  - MR16: México.
  - **Retención de garantía** del contrato (5 % de la base en obra privada).
  - **México:**
    - 5 al millar: 0,5 % de la base, gasto 63100000.
    - Amortización del anticipo: 30 % del total con IVA de cada estimación, hasta agotar el anticipo, contra 43800000.
- **Clientes públicos españoles:** factura electrónica por FACe con los tres códigos DIR3 del maestro de clientes (`oficina_contable`, `organo_gestor`, `unidad_tramitadora`).
- **Servicios municipales:** canon mensual vigente más los servicios extraordinarios **con conformidad** del técnico municipal. Los pendientes de conformidad no se facturan.
- **Revisión de precios:** cuando se aprueba el decreto, se factura la diferencia (canon nuevo − antiguo) de **cada** mes desde la fecha de efectos. Una línea por mes, cuenta 70520000.
- **PPA:** MWh medidos × porcentaje del PPA × precio fijo, con el importe truncado al céntimo.
- **Mercado:** la liquidación del representante, por planta, menos los desvíos.
- **Asiento:**
  - Dr 43000000 por el importe a cobrar (socio cliente, asignación = número de factura).
  - Dr 43000900 por la garantía, Dr 43800000 por la amortización del anticipo y Dr 63100000 por el 5 al millar.
  - Cr a la cuenta de ingresos (70510000 obra, 70500000 servicios, 70520000 revisión, 70530000 energía) con PEP o centro de coste.
  - Cr 47700000 por el IVA.

### 3.2 Aplicación de cobros

Los abonos del extracto ya entraron en Dr 572 / Cr 55500000. Por cada uno se entrega:

- **Aplicaciones:** factura (o pagaré) e importe.
- **Diferencias (`residuals`):**
  - `PENALTY`: penalidad descontada por la administración (Dr 70590000).
  - `NETTING_AP`: compensación con una factura de honorarios del propio cliente, por ejemplo el representante de mercado (Dr a la cuenta del proveedor).
  - `OVERPAYMENT_DUPLICATE`: el cliente pagó dos veces (Cr 43800000, a devolver o compensar).
  - `FACTORED_MISDIRECTED`: el cliente pagó a Kalmora una factura cedida al factor (Cr 55300000 FACTOR-BAE).
  - `NON_CUSTOMER`: no es un cliente. Indemnización de seguro: 75900000. Devolución de fianza: 56500000. Devolución de IVA: 47000000.
- **Asiento de ajuste:** Dr 55500000 / Cr 430 (o 431 o la cuenta de la diferencia).

Si el cliente paga **menos** sin causa conocida, se aplica **parcialmente** a la factura y el resto queda abierto. Los cobros de pagarés al vencimiento se aplican a 43100000 (asignación `PAG<número>`).

## 4. Conciliación bancaria

- **Casación:** se casan las líneas del extracto (`bank_line`) con las líneas del diario en la cuenta 572 de esa cuenta bancaria (`<id asiento>#<línea>`). Puede ser 1:1, N:1 (una remesa contra varios pagos, una nómina en dos lotes) o 1:N.
- **Categorías de lo que queda sin casar:**

| Categoría | Lado | ¿Ajuste? | Asiento |
|---|---|---|---|
| `BANK_FEE_NOT_BOOKED` | banco | sí | Dr 62600000 (comisiones de aval: 66900000) / Cr 572 |
| `INTEREST_NOT_BOOKED` | banco | sí | Dr 572 / Cr 76200000; retención del 19 %: Dr 47300000 / Cr 572 |
| `LOAN_INTEREST_NOT_BOOKED` | banco o diferencia | sí | Dr 66200000 / Cr 572 |
| `CARD_SETTLEMENT_NOT_BOOKED` | banco | sí | Dr 62910000 (CC-1000-DIR) / Cr 572 |
| `DIRECT_DEBIT_NOT_BOOKED` | banco | sí | Dr cuenta del proveedor (asignación = nº de factura) / Cr 572 |
| `RETURNED_DIRECT_DEBIT` | banco | sí | Dr 43000000 cliente (asignación = recibo) / Cr 572, y comisión a 62600000 |
| `FX_RATE_DIFFERENCE` | diferencia | sí | Diferencia entre el cambio del banco y el de referencia: 66800000/76800000 |
| `FACTORING_CHARGES_NOT_BOOKED` | diferencia | sí | Dr 66500000 / Cr 55300000 |
| `POOLING_NOT_BOOKED` | banco | sí | Barrido de cash pooling contra 55200000 (socio 1000) |
| `UNRECORDED_RECEIPT` | banco | sí | No se importó el N43 de ese día: Dr 572 / Cr 55500000 |
| `BOOK_AMOUNT_ERROR` | libro | sí | Corregir la diferencia contra la cuenta del proveedor |
| `WRONG_BANK_ACCOUNT` | libro y banco | sí | Reclasificar entre cuentas 572 |
| `BOOK_DUPLICATE` | libro | sí | Anular el asiento duplicado |
| `BANK_ERROR` | banco | no | Reclamar al banco (cargo duplicado) |
| `OUTSTANDING_PAYMENT` | libro | no | Pago registrado que el banco ejecuta el mes siguiente |
| `TRANSFER_IN_TRANSIT` | libro | no | Traspaso entre cuentas propias pendiente de abono |
| `PRIOR_PERIOD_BANK_ITEM` | libro | no | Registro de un cargo que salió en el extracto del mes anterior |
| `FX_REVALUATION` | libro | no | Valoración o retrocesión de saldos en divisa (no es un movimiento) |

## 5. Cierre del mes

- **`ACCRUAL`**:
  - **Qué se periodifica:** servicios **sin pedido** consumidos y no facturados al cierre: electricidad, agua, telecomunicaciones, combustible, viajes, mensajería, material de oficina, vertedero, consultores y profesionales sin pedido.
  - **Importe:** se estima con el histórico de cada proveedor (los periodos de facturación no coinciden con el mes natural). Tolerancia de ±15 %.
  - **Asiento:** Dr gasto con su objeto de coste / Cr 40090000 con socio el proveedor, con retrocesión automática el día 1.
  - **Lo que no se periodifica:** lo que tiene pedido ya está en la cuenta puente GR/IR.
- **`PREPAID`:**
  - Primas de seguro, arrendamientos rústicos semestrales y cuotas anuales se reparten linealmente entre los meses de cobertura.
  - El mes de la factura se difiere a 48000000 la parte no devengada. Cada mes siguiente se imputa una mensualidad.
  - `amount` = variación del saldo de 48000000: positiva cuando se difiere y negativa cuando se imputa.
- **`WIP_REVENUE`:**
  - Obra ejecutada pendiente de certificar (certificación no aprobada): Dr 43090000 / Cr 71300000 por el importe de la certificación pendiente, con retrocesión el día 1.
- **`FX_REVAL`:**
  - **Qué se valora:** las partidas abiertas en moneda distinta de la local, al tipo SYN-BCE del último día del mes: facturas de proveedor en USD/GBP; en 3100, el préstamo y los intereses en EUR y la cuenta en USD.
  - **Importe:** `amount` = valor a tipo de cierre − valor contable, en moneda local. Positivo si aumenta el valor de la partida.
  - **Asiento:** contra 66800000 o 76800000, con retrocesión el día 1.
- **`BAD_DEBT`:**
  - **Base:** el saldo pendiente de clientes privados y comunidades (las administraciones públicas y el grupo no se deterioran).
  - **Porcentaje:** vencido más de 180 días, 50 %; más de 365 días, 100 %. Cliente en concurso: 100 % de todo su saldo, garantías incluidas.
  - **Asiento:** se ajusta 49000000 (por cliente) contra 69400000 o 79400000. `amount` = provisión necesaria − provisión anterior.
- **`DOUBTFUL_RECLASS`:**
  - En el mes en que se declara el concurso, el saldo pasa de 43000000 a 43600000 factura a factura.

## 6. Intragrupo

- Saldos que deben cuadrar: 43300000↔40300000 (facturas), 55200000 (pooling, préstamo e intereses), 24230000↔16330000 (préstamo 1000→3100) y 55210000↔55220000 (UTE).
- **Facturas en tránsito:** una factura intragrupo emitida y no recibida al cierre la registra el receptor como pendiente de recibir: Dr gasto / Cr 40090000 (socio = sociedad emisora).
- **Intereses del préstamo KMI-2025-01:** 6 % con base **act/360** (días reales del mes / 360). Ambas partes devengan lo mismo en EUR.
- **Causas de diferencia:**

| Causa | Qué pasó |
|---|---|
| `INVOICE_IN_TRANSIT` | Factura emitida y no recibida al cierre |
| `INTEREST_DAY_COUNT` | Los intereses se calcularon con otra base |
| `WRONG_TRADING_PARTNER` | Asiento con otro socio intragrupo |
| `DUPLICATE_POSTING` | Asiento duplicado |
| `POOLING_NOT_BOOKED` | Barrido sin registrar. Se corrige en la conciliación bancaria: aquí sin ajuste |
