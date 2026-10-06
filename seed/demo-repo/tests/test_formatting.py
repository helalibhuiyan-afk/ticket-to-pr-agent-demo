import unittest
from datetime import datetime, timezone

from orders_service.formatting import format_order_date, order_summary
from orders_service.models import Customer, Order


class FormattingTests(unittest.TestCase):
    def test_utc_customer(self):
        ts = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)
        self.assertEqual(format_order_date(ts, 0), "2026-03-01")

    def test_summary(self):
        order = Order(id="o-9", customer=Customer(id="c", name="Lin"),
                      created_at=datetime(2026, 3, 1, 9, 0, tzinfo=timezone.utc))
        self.assertEqual(order_summary(order)["date"], "2026-03-01")
