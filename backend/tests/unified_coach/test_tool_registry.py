"""The published tool set is closed and self-describing.

These tests guard the properties that make the loop tool-agnostic: a tool cannot
be installed at runtime, and a tool cannot advertise itself as read-only while
declaring a write effect.
"""
import pytest
from pydantic import BaseModel, ConfigDict

from backend.agent.tools import registry
from backend.agent.tools.registry import SPECS, tool_descriptions
from backend.agent.tools.spec import ToolAccess, ToolSpec, require_domains


class EchoArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str


def _spec(**overrides):
    values = dict(name="test.echo", args_model=EchoArgs, effect="public_read",
                  handler=lambda args, ctx: {"echo": args.text})
    values.update(overrides)
    return ToolSpec(**values)


def test_the_five_published_tools_are_read_only_and_unchanged():
    assert set(SPECS) == {"skills.search", "resources.read", "fitness.query",
                          "knowledge.search", "fitness.calculate"}
    descriptions = tool_descriptions()
    assert [item["name"] for item in descriptions] == sorted(SPECS)
    assert all(item["read_only"] is True for item in descriptions)


def test_there_is_no_runtime_installation_path():
    # A model that could name a tool to install would be able to widen its own
    # capability set.
    assert not hasattr(registry, "register")
    assert not hasattr(registry, "install")
    assert not hasattr(registry, "add")


def test_draft_write_cannot_claim_to_be_read_only():
    with pytest.raises(ValueError, match="TOOL_READ_ONLY_CONTRADICTION"):
        _spec(name="plan.submit", effect="draft_write", read_only=True)


def test_draft_write_cannot_be_replayed_or_cached():
    with pytest.raises(ValueError, match="DRAFT_WRITE_MUST_NOT_REPLAY"):
        _spec(name="plan.submit", effect="draft_write", read_only=False, replay="safe")
    with pytest.raises(ValueError, match="DRAFT_WRITE_MUST_NOT_CACHE"):
        _spec(name="plan.submit", effect="draft_write", read_only=False,
              replay="never", cacheable=True)


def test_a_draft_write_spec_is_publishable_when_declared_honestly():
    spec = _spec(name="plan.submit", effect="draft_write", read_only=False, replay="never")
    assert spec.describe()["read_only"] is False
    assert spec.public is False


def test_public_read_is_derived_from_the_effect():
    assert _spec().describe()["read_only"] is True
    assert _spec().public is True
    assert _spec(effect="private_read").public is False
    assert _spec(effect="calculate").public is False


@pytest.mark.parametrize("name", ["", "Echo", "test", "test.", ".echo", "test.Echo", "test.echo!"])
def test_tool_names_must_be_lowercase_and_namespaced(name):
    with pytest.raises(ValueError, match="TOOL_NAME_INVALID"):
        _spec(name=name)


def test_default_authorization_requires_the_declared_domains():
    principal = object()
    allowed = ToolAccess(principal=principal, args=None, domains=frozenset({"training"}),
                         required=frozenset({"training"}))
    require_domains(allowed)
    denied = ToolAccess(principal=principal, args=None, domains=frozenset({"training"}),
                        required=frozenset({"diet"}))
    with pytest.raises(PermissionError, match="SCOPE_PERMISSION_REQUIRED"):
        require_domains(denied)


def test_result_limit_is_bounded():
    with pytest.raises(ValueError, match="TOOL_RESULT_LIMIT_INVALID"):
        _spec(max_result_chars=0)
    with pytest.raises(ValueError, match="TOOL_RESULT_LIMIT_INVALID"):
        _spec(max_result_chars=10_000_000)


@pytest.mark.parametrize('fields, expected', [
    (['daily_protein_target'], {'diet'}),
    (['experience_level'], {'training'}),
    (['goal'], {'profile'}),
    (['goal', 'daily_protein_target'], {'profile', 'diet'}),
])
def test_query_domains_follow_the_profile_field_owner(fields, expected):
    from backend.agent.tools.contracts import QueryArgs
    from backend.agent.tools.registry import _query_domains

    args = QueryArgs(domain="profile", fields=fields,
                     start_date="2026-10-01", end_date="2026-10-02")
    assert _query_domains(args) == frozenset(expected)
