from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal


@dataclass
class Coupon:
    code: str
    amount_off: Decimal = Decimal("0")   # fixed amount off the subtotal
    percent_off: Decimal = Decimal("0")  # 0-100


@dataclass
class LineItem:
    sku: str
    unit_price: Decimal
    quantity: int = 1

    @property
    def total(self) -> Decimal:
        return self.unit_price * self.quantity


@dataclass
class Customer:
    id: str
    name: str
    utc_offset_minutes: int = 0  # customer's local timezone offset from UTC


@dataclass
class Order:
    id: str
    customer: Customer
    items: list[LineItem] = field(default_factory=list)
    coupon: Coupon | None = None
    created_at: datetime | None = None  # always timezone-aware, stored in UTC
