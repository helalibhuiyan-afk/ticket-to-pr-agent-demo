"""Scripted OpenAI-compatible LLM for smoke-testing the pipeline without a real model.

It plays the negative-total scenario: investigate, then fix with one deliberately bad edit first
(to exercise the retry path). Run:  uvicorn tests.mock_llm:app --port 9010
and point the agent at LLM_BASE_URL=http://<host>:9010/v1
"""
import json
import os
import uuid

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

FIX_SEARCH = "        amount = amount - coupon.amount_off\n    return amount"
FIX_REPLACE = "        amount = amount - coupon.amount_off\n    return max(amount, Decimal(\"0\"))"
TEST_FILE = '''import unittest
from decimal import Decimal

from orders_service.models import Coupon
from orders_service.pricing import apply_coupon


class CouponClampTest(unittest.TestCase):
    def test_amount_off_larger_than_subtotal_is_zero(self):
        self.assertEqual(apply_coupon(Decimal("15"), Coupon(code="SAVE25", amount_off=Decimal("25"))), Decimal("0"))
'''


def edits(case_id, bad=False):
    fix = {"path": "orders_service/pricing.py", "search": "  return amount  # wrong" if bad else FIX_SEARCH,
           "replace": FIX_REPLACE}
    return [fix, {"path": f"tests/test_case_{case_id}.py", "search": "", "replace": TEST_FILE}]


INVESTIGATOR = [
    ("context_get_case", lambda c: {"case_id": c}),
    ("logs_search", lambda c: {"level": "ERROR"}),
    ("jira_search_tickets", lambda c: {"query": "coupon payment amount", "status": "Done"}),
    ("repo_search_code", lambda c: {"query": "def apply_coupon"}),
    ("repo_read_file", lambda c: {"path": "orders_service/pricing.py"}),
    ("context_submit_investigation", lambda c: {
        "case_id": c, "summary": "Fixed-amount coupons larger than the subtotal produce a negative total.",
        "root_cause": "orders_service/pricing.py apply_coupon subtracts amount_off without clamping at zero, "
                      "so payments.charge raises PaymentError for negative amounts.",
        "evidence": ["payments ERROR: PaymentError: amount must be >= 0 (amount=-10.80)",
                     "pricing DEBUG: subtotal=15.00 amount_off=25.00 discounted=-10.00",
                     "DEMO-12: 'always clamp/validate amounts after discounts'"],
        "proposed_fix": "In apply_coupon, return max(amount, Decimal('0')) after applying amount_off.",
        "files_to_change": ["orders_service/pricing.py"], "confidence": "high"}),
]

DEVELOPER = [
    ("context_get_case", lambda c: {"case_id": c}),
    ("repo_read_file", lambda c: {"path": "orders_service/pricing.py"}),
    ("repo_run_tests", lambda c: {"edits": edits(c, bad=True)}),
    ("repo_run_tests", lambda c: {"edits": edits(c)}),
    ("repo_create_pull_request", lambda c: {"case_id": c, "title": "Clamp coupon discount at zero",
                                            "description": "Fixes negative totals for fixed-amount coupons.",
                                            "edits": edits(c)}),
    ("context_record_pull_request", lambda c: {"case_id": c, "pr_id": "__PR__", "summary": "Clamp coupon discount"}),
]


async def chat(request):
    body = await request.json()
    msgs = body["messages"]
    script = INVESTIGATOR if "INVESTIGATOR" in msgs[0]["content"] else DEVELOPER
    if script is DEVELOPER and os.environ.get("MOCK_FORGET_RECORD"):  # exercise the worker's finalization check
        script = DEVELOPER[:-1]
    case_id = int(msgs[1]["content"].split("Case id:")[1].split()[0])
    tool_msgs = [m for m in msgs if m["role"] == "tool"]
    step = len(tool_msgs)
    if step >= len(script):
        message = {"role": "assistant", "content": "Done."}
    else:
        name, make = script[step]
        args = make(case_id)
        if args.get("pr_id") == "__PR__":
            args["pr_id"] = next(json.loads(m["content"])["pr_id"] for m in tool_msgs if '"pr_id"' in m["content"])
        message = {"role": "assistant", "content": f"Step {step + 1}: calling {name}.",
                   "tool_calls": [{"id": f"call_{uuid.uuid4().hex[:6]}", "type": "function",
                                   "function": {"name": name, "arguments": json.dumps(args)}}]}
    return JSONResponse({"id": "mock", "object": "chat.completion", "model": body["model"],
                         "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
                         "usage": {"prompt_tokens": sum(len(str(m)) for m in msgs) // 4, "completion_tokens": 40}})


app = Starlette(routes=[Route("/v1/chat/completions", chat, methods=["POST"])])
