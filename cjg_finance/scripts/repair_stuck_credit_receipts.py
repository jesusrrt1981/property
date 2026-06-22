"""Reparacion idempotente de recibos POS de credito pegados en `to_distribute`.

Contexto del bug (corregido en cjg_finance/models/pos_payment_receipt_ext.py):
    Antes de este fix, `cjg.pos.payment.receipt.action_confirm()` creaba
    el asiento contable y dejaba el recibo en `to_distribute`, pero NO
    llamaba a `action_quick_collect()`. Resultado: dinero entra a caja, asiento
    contable queda creado, pero la cuota del contrato (`sale.credit.line`) no
    se actualizaba y el recibo quedaba pegado.

Este script encuentra esos recibos huerfanos y aplica la distribucion ahora.

Uso (dentro de odoo-bin shell):
    >>> exec(open('cjg_finance/scripts/repair_stuck_credit_receipts.py').read())

O via xmlrpc:
    models.execute_kw(DB, uid, PWD, 'cjg.pos.payment.receipt',
        'repair_stuck_credit_receipts', [])
"""

# Cuando se ejecuta dentro de odoo shell, `env` esta disponible.
try:
    env  # type: ignore[name-defined]
except NameError:
    raise RuntimeError(
        "Este script debe correrse en odoo-bin shell o como server action."
    )

stuck = env['cjg.pos.payment.receipt'].search([
    ('document_type', '=', 'credit'),
    ('state', '=', 'to_distribute'),
    ('sale_credit_id', '!=', False),
    ('sale_credit_payment_id', '=', False),
    ('amount_paid', '>', 0),
])

print(f"Recibos pegados encontrados: {len(stuck)}")
ok, ko = [], []
for receipt in stuck:
    try:
        receipt.action_quick_collect()
        ok.append(receipt.name or receipt.id)
        print(f"  OK  {receipt.name or receipt.id} ({receipt.amount_paid})")
    except Exception as exc:
        ko.append((receipt.name or receipt.id, str(exc)))
        print(f"  ERR {receipt.name or receipt.id}: {exc}")

env.cr.commit()
print(f"\nRecuperados: {len(ok)} | Fallidos: {len(ko)}")
for name, err in ko:
    print(f"  - {name}: {err}")
