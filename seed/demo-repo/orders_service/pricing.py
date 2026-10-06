from decimal import ROUND_HALF_UP, Decimal

from .models import Coupon, Order

TAX_RATE = Decimal("0.08")
CENT = Decimal("0.01")


def subtotal(order: Order) -> Decimal:
    return sum((item.total for item in order.items), Decimal("0"))


def apply_coupon(amount: Decimal, coupon: Coupon | None) -> Decimal:
    """Return the amount after applying a coupon."""
    if coupon is None:
        return amount
    if coupon.percent_off:
        amount = amount * (Decimal("100") - coupon.percent_off) / Decimal("100")
    if coupon.amount_off:
        amount = amount - coupon.amount_off
    return amount


def tax(amount: Decimal) -> Decimal:
    return (amount * TAX_RATE).quantize(CENT, rounding=ROUND_HALF_UP)


def order_total(order: Order) -> Decimal:
    """Total to charge the customer: subtotal, minus coupon, plus tax."""
    discounted = apply_coupon(subtotal(order), order.coupon)
    return (discounted + tax(discounted)).quantize(CENT, rounding=ROUND_HALF_UP)
