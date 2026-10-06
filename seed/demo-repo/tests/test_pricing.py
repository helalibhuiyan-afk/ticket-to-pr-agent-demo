import unittest
from decimal import Decimal

from orders_service.checkout import checkout
from orders_service.models import Coupon, Customer, LineItem, Order
from orders_service.pricing import apply_coupon, order_total, subtotal


def make_order(*prices, coupon=None):
    return Order(
        id="o-1",
        customer=Customer(id="c-1", name="Ada"),
        items=[LineItem(sku=f"sku-{i}", unit_price=Decimal(p)) for i, p in enumerate(prices)],
        coupon=coupon,
    )


class PricingTests(unittest.TestCase):
    def test_subtotal(self):
        self.assertEqual(subtotal(make_order("10.00", "5.50")), Decimal("15.50"))

    def test_no_coupon(self):
        self.assertEqual(order_total(make_order("100.00")), Decimal("108.00"))

    def test_percent_coupon(self):
        coupon = Coupon(code="TEN", percent_off=Decimal("10"))
        self.assertEqual(order_total(make_order("100.00", coupon=coupon)), Decimal("97.20"))

    def test_amount_coupon(self):
        self.assertEqual(apply_coupon(Decimal("50"), Coupon(code="FIVE", amount_off=Decimal("5"))), Decimal("45"))

    def test_checkout_charges_total(self):
        result = checkout(make_order("20.00"))
        self.assertEqual(result["amount"], "21.60")
        self.assertEqual(result["status"], "captured")
