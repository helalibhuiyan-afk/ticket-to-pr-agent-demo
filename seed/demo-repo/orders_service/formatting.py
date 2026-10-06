from datetime import datetime

from .models import Order


def format_order_date(created_at: datetime, utc_offset_minutes: int = 0) -> str:
    """Format an order timestamp as the customer's local calendar date (YYYY-MM-DD)."""
    return created_at.strftime("%Y-%m-%d")


def order_summary(order: Order) -> dict:
    return {
        "id": order.id,
        "customer": order.customer.name,
        "date": format_order_date(order.created_at, order.customer.utc_offset_minutes),
        "items": len(order.items),
    }
