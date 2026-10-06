from .models import Order
from .payments import charge
from .pricing import order_total


def checkout(order: Order) -> dict:
    """Price the order and charge the customer."""
    total = order_total(order)
    return charge(order.id, total)
