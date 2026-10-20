"""Public, bounded references; never mirror arbitrary runtime trace or prompts."""
from __future__ import annotations

import json
import re

# A business task reference is display-only. Kind and id are the whole contract:
# candidates, budgets and permissions stay inside the business service that owns
# them and are never copied into a chat transcript.
_BUSINESS_TASK_KIND = re.compile(r"[a-z_]{1,40}")
_BUSINESS_TASK_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")


def public_message_metadata(receipt: str | None) -> dict:
    try:
        value = json.loads(receipt or "{}")
    except (TypeError, ValueError):
        return {}
    if not isinstance(value, dict):
        return {}
    result = {}
    if isinstance(value.get("model"), str):
        result["model"] = value["model"][:120]
    sources = value.get("sources")
    if isinstance(sources, list):
        result["sources"] = [
            {key: source[key][:160] for key in ("source", "heading") if isinstance(source.get(key), str)}
            for source in sources[:12] if isinstance(source, dict)
        ]
    reference = value.get("business_task_ref")
    if isinstance(reference, dict):
        kind = reference.get("kind")
        task_id = reference.get("task_id")
        if (isinstance(kind, str) and isinstance(task_id, str)
                and _BUSINESS_TASK_KIND.fullmatch(kind) and _BUSINESS_TASK_ID.fullmatch(task_id)):
            result["business_task_ref"] = {"kind": kind, "task_id": task_id}
    context = value.get("context")
    if isinstance(context, dict):
        result["context"] = {key: context[key][:100] for key in ("action", "surface", "date", "plan_id", "report_week")
                             if isinstance(context.get(key), str)}
        if context.get("admitted_scope") is True:
            result["context"]["admitted_scope"] = True
    return result
