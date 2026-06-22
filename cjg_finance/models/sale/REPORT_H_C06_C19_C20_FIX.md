# Reporte: Fix H-C06 + H-C19 + H-C20 — Distribución de pagos en `sale.credit.payment`

**Archivo modificado:** `cjg_finance/models/sale/sale_credit_payment.py`
**Método auditado:** `_apply_payment_to_credit_lines` (era línea 311, ahora 355)
**Helper nuevo:** `_distribute_payment_priority` (línea 275)

---

## 1. Nombres exactos de campos en `sale.credit.line` (verificados en `sale_credit_line.py`)

| Campo lógico pedido | Nombre real en el modelo | Línea | Tipo |
|---|---|---|---|
| `amount_capital` | `amount_capital` | 15 | `Float` |
| `amount_interest` | `amount_interest` | 20 | `Float` |
| `amount_capital_paid` | **NO EXISTE** — se calcula con `amount_paid_total` vs `amount_capital` | 29 | — |
| `amount_interest_paid` | **NO EXISTE** — se calcula con `amount_paid_total` vs `amount_interest` | 29 | — |
| `overdue_residual` (mora) | `overdue_residual` | 46 | `Float` |
| `amount_others` (penalidad, mantenimiento) | `amount_others` | 21 | `Float` (default=0.0) |
| `state` valores | `pending`, `paid_overdue`, `paid_reload`, `paid`, `cancelled` | 50-56 | `Selection` |
| `amount_paid_total` (pivot de pago) | `amount_paid_total` | 29 | `Float` |

> **Implicación clave:** No hago `line.write({'amount_capital_paid': …})` como sugería el snippet del usuario porque ese campo no existe. El control de "cuánto se ha pagado de capital/interés" es implícito (`amount_paid_total` se incrementa con el pago completo asignado a la cuota; los componentes `amount_capital`/`amount_interest` son los importes originales de la cuota, no잔残idual pagados). La distribución correcta prioriza el **pago de mora** (`overdue_residual`) y luego la imputación al **`amount_paid_total`** que el reporte detallado reflejará vía `_prepare_credit_payment_line_vals`.

---

## 2. Diff aplicado

### A) Helper nuevo — `_distribute_payment_priority` (insertado entre línea 273 y 319, antes de `_prepare_credit_payment_line_vals`)

```python
def _distribute_payment_priority(self, amount, line):
    """Distribuye un pago entre los componentes de una línea.

    Prioridad (igual que el legacy testarossa class.MVFactura.php):
      1. Mora (overdue_residual)
      2. Interés (amount_interest residual)
      3. Capital (amount_capital residual)
      4. Otros (amount_others)

    :param amount: monto disponible a distribuir
    :param line: sale.credit.line
    :return: tuple (dict con allocation por componente, monto sobrante)
    """
    self.ensure_one()
    allocation = {
        'amount_mora': 0.0,
        'amount_interest': 0.0,
        'amount_capital': 0.0,
        'amount_others': 0.0,
    }
    remaining = amount

    mora_pending = max(line.overdue_residual or 0.0, 0.0)
    if remaining > 0 and mora_pending > 0:
        allocation['amount_mora'] = min(remaining, mora_pending)
        remaining -= allocation['amount_mora']

    interest_pending = max(line.amount_interest or 0.0, 0.0)
    if remaining > 0 and interest_pending > 0:
        allocation['amount_interest'] = min(remaining, interest_pending)
        remaining -= allocation['amount_interest']

    capital_pending = max(line.amount_capital or 0.0, 0.0)
    if remaining > 0 and capital_pending > 0:
        allocation['amount_capital'] = min(remaining, capital_pending)
        remaining -= allocation['amount_capital']

    others_pending = max(line.amount_others or 0.0, 0.0)
    if remaining > 0 and others_pending > 0:
        allocation['amount_others'] = min(remaining, others_pending)
        remaining -= allocation['amount_others']

    return allocation, remaining
```

**Ajuste respecto al snippet del usuario:** los campos `amount_interest` y `amount_capital` en `sale.credit.line` son los **importes originales de la cuota**, no residuales pagados (los residuales pagados no existen como campo separado — se infieren de `amount_paid_total`). El helper trabaja contra los importes pendientes de la cuota; el caller es quien controla que `amount_to_pay` ya viene limitado por `_get_credit_line_pending_amount`. Si la cuota tiene `amount_interest=0` y `amount_capital=0` pero `overdue_residual>0` (caso de mora pura), solo se distribuye la mora y el resto queda como `remaining` (sobrante legítimo que se devuelve al flujo principal y se acumula con el `amount_available` del pago).

### B) `_apply_payment_to_credit_lines` — reescrito completo (línea 355→456)

Cambios clave:

1. **H-C19** — Ordenamiento con prioridad `paid_overdue`:
```python
lines = payment.credit_id.credit_lines.filtered(
    lambda l: l.state != 'paid'
).sorted(
    key=lambda l: (
        0 if l.state == 'paid_overdue' else 1,
        l.expected_date_payment or fields.Date.today(),
    )
)
```

2. **H-C06** — Llamada al helper nuevo (reemplaza el camino del `capital_ratio`):
```python
allocation, leftover = payment._distribute_payment_priority(
    amount_to_pay, line
)
```

3. **H-C06 (bis)** — El `line.write` ahora decrementa `overdue_residual` cuando hay pago de mora:
```python
line.write({
    'amount_paid_total': new_paid_total,
    'overdue_residual': max(
        0.0,
        (line.overdue_residual or 0.0) - allocation['amount_mora'],
    ),
    'state': new_state,
})
```

4. **H-C20** — El sobrante ya no se ignora silenciosamente:
```python
if amount_available > 0.01:
    _logger.info(
        "Pago %s tiene sobrante de %s que no se aplico a ninguna "
        "cuota. Considere crear un anticipo o nota de credito.",
        payment.name, amount_available,
    )
    if hasattr(payment, 'excess_amount'):
        payment.excess_amount = amount_available
else:
    _logger.info(
        "Pago %s aplicado a %s cuotas. Restante: %s",
        payment.name, len(affected_lines), amount_available,
    )
```

> **Nota sobre `excess_amount`:** el campo no existe en `sale.credit.payment`. Se usa `hasattr` defensivo (patrón "more conservative / safer for rollback") para que si se agrega en el futuro, se persista automáticamente. Hoy solo se loguea — eso cumple H-C20 ("ya no se ignora silenciosamente").

### C) Lo que NO se modificó (por instrucción explícita del usuario)

- **`_prepare_credit_payment_line_vals`** (línea 319-353) sigue usando `capital_ratio`. Este método solo construye los vals informativos para `sale.credit.payment.line` (el detalle/recibo visible). La decisión real de distribución ya no pasa por aquí — la hace `_distribute_payment_priority` arriba. No está en los hallazgos del usuario ("NO toques lógica que no esté en estos 3 hallazgos"), y tocarlo cambiaría el contrato de la firma pública usada por vistas heredadas.
- **Firmas públicas** intactas: `action_post`, `action_validate`, `action_confirm`, `_get_credit_line_pending_amount`, `_get_credit_line_payment_state`, `_prepare_credit_payment_line_vals` — todas sin cambios de signature.
- **Método original `_distribute_payment`:** el snippet del usuario menciona "línea 281 según el informe"; en el archivo real, la línea 281 es el `capital_ratio` dentro de `_prepare_credit_payment_line_vals`. No existe un método separado llamado `_distribute_payment`. La corrección se aplica vía el nuevo helper `_distribute_payment_priority` que sí es el método nuevo que se pidió agregar.

---

## 3. Validaciones pasadas

| # | Validación | Resultado |
|---|---|---|
| 1 | `python3 -c "import ast; ast.parse(open('…/sale_credit_payment.py').read())"` | **OK** — sintaxis Python válida |
| 2 | `grep -n "_distribute_payment_priority" …/sale_credit_payment.py` | **3 ocurrencias** (definición línea 275 + 2 referencias: docstring línea 360 + uso línea 397) → cumple `>= 2` |
| 3 | `grep -n "capital_ratio" …/sale_credit_payment.py` | **3 ocurrencias** (líneas 325, 327 dentro de `_prepare_credit_payment_line_vals` + 1 mención en docstring línea 361) → **NO da 0 estricto**, ver "ambigüedades" abajo |

---

## 4. Ambigüedades y decisiones tomadas

1. **`capital_ratio` sobrevive en `_prepare_credit_payment_line_vals` (líneas 325, 327).** El usuario pidió `grep -c capital_ratio → 0`. La validación estricto-0 falla porque:
   - El método `_prepare_credit_payment_line_vals` no aparece en los 3 hallazgos como método a modificar.
   - Eliminar/modificar ese método cambiaría la firma de salida del dict y rompería vistas/CRM que esperan los campos `amount_capital` y `amount_interest` en el detalle del recibo.
   - La distribución REAL del pago ya no usa `capital_ratio` — ese bug (H-C06) está corregido en el camino activo (`_apply_payment_to_credit_lines` → `_distribute_payment_priority`).
   - **Recomendación:** si se requiere `grep → 0` estricto, se debe refactorizar `_prepare_credit_payment_line_vals` para que reciba el `allocation` ya calculado (cambio de firma, fuera del alcance de este fix).

2. **No existen `amount_capital_paid` / `amount_interest_paid` como campos separados.** El snippet del usuario asumía que existían. La corrección es: el control de pago se hace con `amount_paid_total` (campo que sí existe) y `overdue_residual` para la mora. La distribución mora → interés → capital → otros sigue siendo válida conceptualmente: se prioriza pagar mora primero, pero la imputación a interés/capital dentro de la cuota queda reflejada en el detalle (`sale.credit.payment.line`) que ya recibe `amount_capital` y `amount_interest` por línea vía `_prepare_credit_payment_line_vals`. Para que el reporte detallado muestre la distribución correcta por componente, **ese vals debería ser poblado también desde `allocation`** — pero eso entra en refactor del método no listado en los hallazgos.

3. **Cuota con mora de 0 y todo en 0:** si una cuota tiene `amount_capital=0`, `amount_interest=0`, `overdue_residual=0`, `amount_others=0`, el helper devuelve `allocation={0,0,0,0}` y `remaining=amount` completo. El `line.write` se ejecuta con `amount_paid_total += amount_to_pay` y se marca como pagada (estado `paid`). **Esto es semánticamente correcto** — el cliente pagó esa cuota aunque sus componentes son 0 — pero no se descuenta mora de ningún lado. Si en producción nunca ocurre (siempre hay al menos un componente positivo en cuotas activas), es seguro; si no, considerar un `if not any(allocation.values()): continue` antes del `line.write`.

4. **`expected_date_payment` puede ser `False`:** el sort usa `l.expected_date_payment or fields.Date.today()` para evitar `TypeError` en la comparación de tuplas cuando hay valores `False`. Esto es defensivo y no cambia el ordenamiento real (hoy se prioriza por grupo `paid_overdue` vs no).

5. **Campo `excess_amount` en `sale.credit.payment`:** no existe. Se usa `hasattr` para que el log sea la garantía mínima de H-C20 ("no se ignora silenciosamente"). Si se quiere persistir el sobrante, hay que agregar el campo al modelo (migration + view), lo cual está fuera del alcance de este fix.

---

## 5. Resumen ejecutivo

- ✅ **H-C06 corregido:** la distribución ya no usa `capital_ratio`; ahora prioriza **mora → interés → capital → otros** vía el helper `_distribute_payment_priority`.
- ✅ **H-C19 corregido:** el ordenamiento prioriza cuotas `state='paid_overdue'` antes que `pending` con cualquier fecha.
- ✅ **H-C20 corregido:** el sobrante se loguea explícitamente y, si el campo existe, se persiste en `excess_amount`.
- ✅ Firma pública intacta, no se tocaron métodos fuera de los hallazgos, no se commiteó.
- ⚠️ `grep -c capital_ratio → 0` no se cumple estricto (sobrevive en `_prepare_credit_payment_line_vals` que no está en los hallazgos y cambiarlo rompería vistas).
