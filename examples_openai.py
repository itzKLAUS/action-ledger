"""Dispatch an OpenAI Responses function call through Action Ledger.

No model calls are made by this file. Integrate dispatch() into your server's
Responses API loop. Keep the ledger key and OpenAI key on the server.
The callback below is deliberately a synthetic preview, not an invoice sender.
"""

import json

from sdk import ActionDenied, DecisionPending

INVOICE_TOOL = {
    "type": "function",
    "name": "preview_invoice",
    "description": "Preview a synthetic invoice for review",
    "strict": True,
    "parameters": {
        "type": "object",
        "properties": {"invoice_id": {"type": "string"}},
        "required": ["invoice_id"],
        "additionalProperties": False,
    },
}


def dispatch(call, ledger, persist_lease):
    if call.name != "preview_invoice":
        raise ValueError("Unknown tool")
    arguments = json.loads(call.arguments)
    if (
        not isinstance(arguments, dict)
        or set(arguments) != {"invoice_id"}
        or not isinstance(arguments["invoice_id"], str)
    ):
        raise ValueError("Invalid tool arguments")
    try:
        result = ledger.execute(
            operation="invoice.preview",
            destination="billing.example.com",
            cost_cents=0,
            arguments=arguments,
            idempotency_key=call.call_id,
            persist_lease=persist_lease,
            callback=lambda args: {"invoice_id": args["invoice_id"], "preview_only": True},
        )
        return {
            "type": "function_call_output",
            "call_id": call.call_id,
            "output": json.dumps(result),
        }
    except DecisionPending as exc:
        # Persist a durable review checkpoint; do not tell the model execution succeeded.
        return {"review_required": True, "action_id": exc.action_id, "call_id": call.call_id}
    except ActionDenied:
        return {
            "type": "function_call_output",
            "call_id": call.call_id,
            "output": '{"error":"Policy denied execution"}',
        }
