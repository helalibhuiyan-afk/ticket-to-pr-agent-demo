from decimal import Decimal


class PaymentError(Exception):
    pass


def charge(order_id: str, amount: Decimal) -> dict:
    """Charge the customer (fake payment gateway)."""
    if amount < 0:
        raise PaymentError(f"amount must be >= 0 (order={order_id}, amount={amount})")
    return {"order_id": order_id, "amount": str(amount), "status": "captured"}
