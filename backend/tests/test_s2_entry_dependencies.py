"""Editing one dish must not re-resolve the others.

The claim "renaming 面 to 粉 only touches that dish and the meal total" is checked
twice: the graph says which nodes are affected, and a spy records which items the
entry service actually resolved. If the two disagree, one of them is wrong and
the draft is doing work nobody asked for.
"""
from __future__ import annotations

import json
from uuid import uuid4

from backend.config import get_settings
from backend.domain.task_dependencies import Node, affected_nodes, graph_edges
from backend.task_evaluation.contracts import Scenario
from backend.task_evaluation.seeding import seed_environment
from backend.tests.task_evaluation.test_runner import _build_client

CATALOG = {"foods": [
    {"source_record_id": "dep-noodles", "name": "面条", "calories": 280, "carbs": 58,
     "protein": 8, "fat": 1},
    {"source_record_id": "dep-milktea", "name": "奶茶", "calories": 90, "carbs": 14,
     "protein": 1, "fat": 3},
]}


def _nodes(item_ids):
    """One chain per dish, plus the total that reads every chain."""
    nodes = []
    for item_id in item_ids:
        nodes.append(Node(f"{item_id}.match", _key(item_id)))
        nodes.append(Node(f"{item_id}.portion", _key(item_id), (f"{item_id}.match",)))
        nodes.append(Node(f"{item_id}.nutrition", _key(item_id), (f"{item_id}.portion",)))
    nodes.append(Node("meal.total", _key("total"),
                      tuple(f"{item_id}.nutrition" for item_id in item_ids)))
    return tuple(nodes)


def _key(resource_id):
    from backend.domain.task_dependencies import DependencyKey
    return DependencyKey(scope="task:draft", resource_id=resource_id,
                         resource_revision="v1", constraints_revision="c1",
                         catalog_revision="cat1", processor_revision="p1")


def test_renaming_one_dish_does_not_resolve_the_other(tmp_path, monkeypatch):
    monkeypatch.setenv("INTERACTIVE_ENTRY_ENABLED", "true")
    monkeypatch.setenv("LLM_ENABLED", "false")
    client = _build_client(tmp_path, monkeypatch)
    settings = get_settings()
    scenario = Scenario.model_validate({"id": "deps", "version": 1,
                                        "initial_state": {"catalog": CATALOG}})
    actors = seed_environment(client, scenario, settings.data_dir)
    headers = actors["primary"]

    resolved = []
    from backend.application.use_cases import interactive_entry

    original = interactive_entry.resolve_item

    def spy(item, food=None, *, updates=None, increment=False):
        resolved.append(item.item_id)
        return original(item, food, updates=updates, increment=increment)

    monkeypatch.setattr(interactive_entry, "resolve_item", spy)

    response = client.post("/api/v1/smart-entry-drafts", headers=headers,
                           json={"log_date": "2026-10-16",
                                 "raw_text": "早餐：面条 100g\n午餐：奶茶 300g"})
    assert response.status_code == 200, response.json()
    draft = response.json()["data"]
    draft = _post(client, draft, "interaction/start", {}, headers)
    items = draft["payload"]["interaction"]["items"]
    assert [item["state"] for item in items] == ["ready", "ready"]
    noodles, milktea = items[0], items[1]

    resolved.clear()
    draft = _post(client, draft, "interaction/corrections",
                  {"item_id": noodles["item_id"], "item_revision": noodles["revision"],
                   "updates": {"name": "米粉"}}, headers)
    assert response.status_code == 200

    # What the service actually did.
    assert set(resolved) == {noodles["item_id"]}
    assert milktea["item_id"] not in resolved

    # What the graph says should be affected, for the same change.
    affected = affected_nodes({f"{noodles['item_id']}.match"}, graph_edges(_nodes(
        [noodles["item_id"], milktea["item_id"]])))
    assert affected == {f"{noodles['item_id']}.match", f"{noodles['item_id']}.portion",
                        f"{noodles['item_id']}.nutrition", "meal.total"}
    assert milktea["item_id"] not in " ".join(affected)


def _post(client, draft, route, body, headers):
    response = client.post(f"/api/v1/smart-entry-drafts/{draft['id']}/{route}",
                           headers={**headers, "Idempotency-Key": str(uuid4())},
                           json={"expected_version": draft["version"], **body})
    assert response.status_code == 200, response.json()
    return response.json()["data"]
