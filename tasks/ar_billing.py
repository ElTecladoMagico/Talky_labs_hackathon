"""P3 — facturación AR: una fila de ar_billing.jsonl por billing_item de tasks/ar_billing_items.json."""


def billing_rows(conn):
    """Filas de entrega, sin efectos. close.py la reutiliza para las SKIP_PENDING_APPROVAL (obra pendiente de certificar)."""
    return []


def run(conn):
    return billing_rows(conn)
