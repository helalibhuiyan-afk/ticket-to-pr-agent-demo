"""Scripted OpenAI-compatible "LLM" for fast demos and smoke tests.

It plays back a realistic investigation and fix for each demo scenario in seed/scenarios.yaml,
calling the same MCP tools a real model would. The scenario is recognized from the ticket text
returned by the first tool call (context_get_case). Tickets that match no scenario get an honest
low-confidence investigation and a PR that only adds a skipped reproduction-test placeholder.

Run:  uvicorn tests.mock_llm:app --port 9010   and point the agent at http://<host>:9010/v1
MOCK_DELAY_SECONDS (default 0.8) adds a short pause per step so the UI timeline is easy to follow.
"""
import asyncio
import json
import os
import uuid

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

DELAY = float(os.environ.get("MOCK_DELAY_SECONDS", "0.8"))
FORGET_RECORD = bool(os.environ.get("MOCK_FORGET_RECORD"))  # exercises the worker's finalization check

# ---------------------------------------------------------------- scenario knowledge

SCENARIOS = {
    "negative-total": {
        "keywords": ["coupon", "checkout"],
        "log_query": {"level": "ERROR"},
        "history_query": "coupon discount amount payment",
        "code_query": "def apply_coupon",
        "file": "orders_service/pricing.py",
        "investigation": {
            "summary": "Fixed-amount coupons larger than the order subtotal produce a negative total, and the payment gateway rejects it.",
            "root_cause": "orders_service/pricing.py: apply_coupon() subtracts coupon.amount_off without clamping the result at zero. "
                          "For a 15.00 order with SAVE25 the discounted amount is -10.00, the total is -10.80, and payments.charge() "
                          "raises PaymentError('amount must be >= 0').",
            "evidence": [
                "pricing DEBUG: order_total subtotal=15.00 coupon=SAVE25 amount_off=25.00 discounted=-10.00 total=-10.80",
                "payments ERROR: PaymentError: amount must be >= 0 (amount=-10.80) at orders_service/payments.py:charge",
                "Orders above the coupon value (subtotal=120.00) are charged normally",
                "DEMO-12 resolution: 'always clamp/validate amounts after discounts'",
            ],
            "proposed_fix": "In apply_coupon(), return max(amount, Decimal('0')) after applying amount_off so a discount can never "
                            "make the amount negative. Add a regression test for a coupon larger than the subtotal.",
            "files_to_change": ["orders_service/pricing.py"],
            "confidence": "high",
        },
        "edits": [{
            "path": "orders_service/pricing.py",
            "search": "        amount = amount - coupon.amount_off\n    return amount",
            "replace": "        amount = amount - coupon.amount_off\n    return max(amount, Decimal(\"0\"))",
        }],
        "bad_search": "    return amount  # after coupon",
        "test": '''import unittest
from decimal import Decimal

from orders_service.checkout import checkout
from orders_service.models import Coupon, Customer, LineItem, Order
from orders_service.pricing import apply_coupon


class CouponLargerThanSubtotalTest(unittest.TestCase):
    def test_discount_never_goes_below_zero(self):
        coupon = Coupon(code="SAVE25", amount_off=Decimal("25"))
        self.assertEqual(apply_coupon(Decimal("15"), coupon), Decimal("0"))

    def test_checkout_succeeds(self):
        order = Order(id="o-1", customer=Customer(id="c-1", name="Ada"),
                      items=[LineItem(sku="a", unit_price=Decimal("15.00"))],
                      coupon=Coupon(code="SAVE25", amount_off=Decimal("25")))
        self.assertEqual(checkout(order)["amount"], "0.00")
''',
        "title": "Clamp coupon discounts at zero so checkout never charges a negative amount",
    },
    "pagination-gap": {
        "keywords": ["order history", "per page", "missing orders", "19 orders"],
        "log_query": {"level": "WARN", "query": "page"},
        "history_query": "order history page duplicate pagination",
        "code_query": "def paginate",
        "file": "orders_service/pagination.py",
        "investigation": {
            "summary": "Each order-history page returns one item fewer than the page size, so one order per page is never shown.",
            "root_cause": "orders_service/pagination.py: paginate() computes end = start + page_size - 1. Python slices already "
                          "exclude the end index, so items[start:end] returns page_size - 1 items and skips the last item of every page.",
            "evidence": [
                "orders-api WARN: page size mismatch page=1 requested=20 returned=19 (orders_service.pagination.paginate)",
                "orders-api WARN: order never served order_index=19 not present on page 1 or page 2",
                "pagination.py line 11: end = start + page_size - 1",
                "DEMO-7 resolution: 'slice end must be start + page_size because Python slices exclude the end index'",
            ],
            "proposed_fix": "Change the slice end to start + page_size. Add a regression test that 40 items give two full pages "
                            "of 20 with no gaps.",
            "files_to_change": ["orders_service/pagination.py"],
            "confidence": "high",
        },
        "edits": [{
            "path": "orders_service/pagination.py",
            "search": "    end = start + page_size - 1\n",
            "replace": "    end = start + page_size\n",
        }],
        "bad_search": "    end = start + page_size - 1  # exclusive\n",
        "test": '''import unittest

from orders_service.pagination import paginate


class PaginationGapTest(unittest.TestCase):
    def test_full_pages_without_gaps(self):
        items = list(range(40))
        page1 = paginate(items, page=1, page_size=20)["items"]
        page2 = paginate(items, page=2, page_size=20)["items"]
        self.assertEqual(len(page1), 20)
        self.assertEqual(page1 + page2, items)
''',
        "title": "Fix off-by-one in paginate() that dropped the last item of every page",
    },
    "tz-date": {
        "keywords": ["wrong day", "dates show", "tomorrow", "calendar day"],
        "log_query": {"query": "rendered_date"},
        "history_query": "date timezone wrong day report",
        "code_query": "def format_order_date",
        "file": "orders_service/formatting.py",
        "investigation": {
            "summary": "Order dates are formatted in UTC instead of the customer's local time, so late-evening US orders show the next day.",
            "root_cause": "orders_service/formatting.py: format_order_date() calls created_at.strftime() on the UTC timestamp and "
                          "ignores its utc_offset_minutes argument. 2026-03-01T04:30Z is 2026-02-28 20:30 for a UTC-8 customer "
                          "but renders as 2026-03-01.",
            "evidence": [
                "orders-api INFO: created_at=2026-03-01T04:30:00+00:00 customer_utc_offset_minutes=-480 rendered_date=2026-03-01",
                "support-tool WARN: expected_date=2026-02-28 shown_date=2026-03-01 (orders_service.formatting.format_order_date)",
                "UK customers (offset 0) are unaffected",
                "DEMO-15 resolution: convert with the customer's UTC offset before formatting the date",
            ],
            "proposed_fix": "Convert created_at to the customer's timezone with "
                            "astimezone(timezone(timedelta(minutes=utc_offset_minutes))) before formatting. Add a regression test "
                            "for a UTC-8 customer.",
            "files_to_change": ["orders_service/formatting.py"],
            "confidence": "high",
        },
        "edits": [
            {"path": "orders_service/formatting.py",
             "search": "from datetime import datetime\n",
             "replace": "from datetime import datetime, timedelta, timezone\n"},
            {"path": "orders_service/formatting.py",
             "search": "    return created_at.strftime(\"%Y-%m-%d\")",
             "replace": "    local = created_at.astimezone(timezone(timedelta(minutes=utc_offset_minutes)))\n"
                        "    return local.strftime(\"%Y-%m-%d\")"},
        ],
        "bad_search": "    return created_at.strftime('%Y-%m-%d')",
        "test": '''import unittest
from datetime import datetime, timezone

from orders_service.formatting import format_order_date


class OrderDateTimezoneTest(unittest.TestCase):
    def test_us_evening_order_keeps_local_date(self):
        ts = datetime(2026, 3, 1, 4, 30, tzinfo=timezone.utc)  # 8:30 PM on Feb 28 in UTC-8
        self.assertEqual(format_order_date(ts, -480), "2026-02-28")

    def test_utc_customer_unchanged(self):
        ts = datetime(2026, 3, 1, 4, 30, tzinfo=timezone.utc)
        self.assertEqual(format_order_date(ts, 0), "2026-03-01")
''',
        "title": "Format order dates in the customer's timezone",
    },
}


def detect(messages: list[dict]) -> str | None:
    # Only the first tool result (context_get_case: the ticket itself); later results include noisy logs.
    first = next((m for m in messages if m["role"] == "tool"), None)
    text = str(first.get("content", "")).lower() if first else ""
    for sid, sc in SCENARIOS.items():
        if any(k in text for k in sc["keywords"]):
            return sid
    return None


def unknown_test(case_id: int, ticket_key: str) -> str:
    return f'''import unittest


class Case{case_id}ReproductionTest(unittest.TestCase):
    @unittest.skip("TODO: reproduce {ticket_key}; the mock LLM could not identify a root cause")
    def test_reproduce(self):
        pass
'''


# ---------------------------------------------------------------- scripts

def investigator_steps(case_id: int, sid: str | None):
    if sid is None:
        return [
            ("Let me start by reading the case and the ticket.", "context_get_case", {"case_id": case_id}),
            ("I'll scan recent warnings and errors across services.", "logs_search", {"level": "WARN"}),
            ("Nothing obvious yet. Let me check for similar resolved tickets.", "jira_search_tickets",
             {"query": "error failure bug", "status": "Done"}),
            ("I couldn't tie this ticket to a specific defect. I'll report what I found with low confidence.",
             "context_submit_investigation", {
                 "case_id": case_id,
                 "summary": "No clear root cause found in the logs or code for this ticket.",
                 "root_cause": "Unknown. The mock LLM only has scripted knowledge of the demo scenarios; switch to the real LLM "
                               "for free-form tickets.",
                 "evidence": ["No log lines matched the ticket's symptoms", "No similar resolved ticket found"],
                 "proposed_fix": "Add a skipped reproduction test as a placeholder and gather more information.",
                 "files_to_change": [f"tests/test_case_{case_id}.py"], "confidence": "low"}),
        ]
    sc = SCENARIOS[sid]
    return [
        ("Let me start by reading the case and the ticket.", "context_get_case", {"case_id": case_id}),
        ("The symptoms point at a specific code path. Let me look at the logs.", "logs_search", sc["log_query"]),
        ("The logs show a clear pattern. Let me check whether we've seen something similar before.",
         "jira_search_tickets", {"query": sc["history_query"], "status": "Done"}),
        ("A past ticket describes a related bug. Let me find the code.", "repo_search_code", {"query": sc["code_query"]}),
        ("Found it. Reading the file to confirm.", "repo_read_file", {"path": sc["file"]}),
        ("Confirmed in the code. Submitting the investigation for review.", "context_submit_investigation",
         {"case_id": case_id, **sc["investigation"]}),
    ]


def developer_steps(case_id: int, sid: str | None, ticket_key: str):
    if sid is None:
        test_edit = [{"path": f"tests/test_case_{case_id}.py", "search": "", "replace": unknown_test(case_id, ticket_key)}]
        return [
            ("Reading the approved investigation.", "context_get_case", {"case_id": case_id}),
            ("Adding the placeholder reproduction test and running the suite.", "repo_run_tests", {"edits": test_edit}),
            ("Tests pass. Opening the pull request.", "repo_create_pull_request", {
                "case_id": case_id, "title": f"Add reproduction-test placeholder for {ticket_key}",
                "description": f"{ticket_key}: no root cause identified yet. Adds a skipped test to track reproduction.",
                "edits": test_edit}),
            ("Linking the PR to the case.", "context_record_pull_request", {"case_id": case_id, "pr_id": "__PR__"}),
        ]
    sc = SCENARIOS[sid]
    test_edit = {"path": f"tests/test_case_{case_id}.py", "search": "", "replace": sc["test"]}
    good = sc["edits"] + [test_edit]
    bad = [dict(sc["edits"][-1], search=sc["bad_search"])] + [test_edit]
    inv = sc["investigation"]
    return [
        ("Reading the approved investigation.", "context_get_case", {"case_id": case_id}),
        ("Reading the file I need to change.", "repo_read_file", {"path": sc["file"]}),
        ("Trying the fix together with a regression test.", "repo_run_tests", {"edits": bad}),
        ("My search text didn't match the file exactly. Copying it verbatim from the file and retrying.",
         "repo_run_tests", {"edits": good}),
        ("All tests pass, including the new regression test. Opening the pull request.", "repo_create_pull_request", {
            "case_id": case_id, "title": sc["title"],
            "description": f"Fixes {ticket_key}.\n\nRoot cause: {inv['root_cause']}\n\nFix: {inv['proposed_fix']}",
            "edits": good}),
        ("Linking the PR to the case.", "context_record_pull_request",
         {"case_id": case_id, "pr_id": "__PR__", "summary": sc["title"]}),
    ]


# ---------------------------------------------------------------- endpoint

async def chat(request):
    body = await request.json()
    msgs = body["messages"]
    first_user = msgs[1]["content"]
    case_id = int(first_user.split("Case id:")[1].split()[0])
    ticket_key = first_user.split("Ticket:")[1].split()[0] if "Ticket:" in first_user else f"case {case_id}"
    is_investigator = "INVESTIGATOR" in msgs[0]["content"]
    sid = detect(msgs)
    steps = investigator_steps(case_id, sid) if is_investigator else developer_steps(case_id, sid, ticket_key)
    if not is_investigator and FORGET_RECORD:
        steps = steps[:-1]
    tool_msgs = [m for m in msgs if m["role"] == "tool"]
    step = len(tool_msgs)
    await asyncio.sleep(DELAY)
    if step >= len(steps):
        message = {"role": "assistant", "content": "Done."}
    else:
        text, name, args = steps[step]
        args = json.loads(json.dumps(args))
        if args.get("pr_id") == "__PR__":
            args["pr_id"] = next((json.loads(m["content"]).get("pr_id") for m in reversed(tool_msgs)
                                  if '"pr_id"' in m["content"]), "PR-0")
        message = {"role": "assistant", "content": text,
                   "tool_calls": [{"id": f"call_{uuid.uuid4().hex[:8]}", "type": "function",
                                   "function": {"name": name, "arguments": json.dumps(args)}}]}
    prompt_tokens = sum(len(str(m.get("content", ""))) for m in msgs) // 4
    return JSONResponse({"id": f"mock-{uuid.uuid4().hex[:8]}", "object": "chat.completion", "model": "scripted-mock",
                         "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
                         "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": 40}})


async def health(request):
    return JSONResponse({"status": "ok", "service": "mock-llm"})


app = Starlette(routes=[Route("/v1/chat/completions", chat, methods=["POST"]), Route("/health", health)])
