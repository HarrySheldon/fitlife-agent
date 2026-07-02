from __future__ import annotations

from backend.tools.report_generator import generate_next_week_plan


def generate_plan(profile: dict) -> dict:
    return generate_next_week_plan(profile)
