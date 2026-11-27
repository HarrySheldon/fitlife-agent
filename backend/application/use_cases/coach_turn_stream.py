"""In-memory per-turn Server-Sent Events (SSE) progress bus and redacted formatters.

Safety invariant:
- Only low-cardinality stage/tool/lifecycle identifiers may be emitted while a turn is
  running. User prompts, raw records, and unreviewed drafts never cross this stream.
- Answer text chunks (`answer_delta`) are emitted ONLY after the coach turn service
  confirms `review_status == 'approved'` and commits the turn.
"""
from __future__ import annotations

import asyncio
import json
import math
import time
from collections import deque
from dataclasses import dataclass, field
from threading import Lock
from typing import Any, Callable

SSE_KEEPALIVE_SECONDS = 15.0
_MAX_EVENTS_PER_TURN = 256
_CHANNEL_TTL_SECONDS = 300.0
_DEFAULT_CHUNK_SIZE = 48

_STAGE_MAP = {
    "queued": "queued",
    "running": "running",
    "stopping": "stopping",
    "input_guard": "input_guard",
    "context_guard": "context_guard",
    "context_loader": "context_loader",
    "planner": "planner",
    "safety_reviewer": "safety_reviewer",
    "output_guard": "output_guard",
    "public_result_projector": "publishing",
    "agent_decision_model": "reasoning",
    "plan_route_model": "planning",
    "write_answer_model": "drafting",
    "safety_review_model": "reviewing",
    "skills.search": "skill_search",
    "resources.read": "skill_read",
    "fitness.query": "reading_records",
    "knowledge.search": "knowledge_search",
    "fitness.calculate": "calculating",
    "catalog.search_foods": "catalog_search",
    "catalog.search_exercises": "catalog_search",
    "fitness.progress": "reading_progress",
    "plan.read_base": "reading_plan",
    "plan.submit_candidate": "preparing_candidate",
}

_SAFE_TOOLS = frozenset(_STAGE_MAP) | frozenset(
    {"load_profile", "analyze_meals", "analyze_workouts", "retrieve_knowledge",
     "generate_weekly_report", "generate_next_week_plan", "validate_plan", "other"}
)


@dataclass(frozen=True)
class StreamEvent:
    id: int
    event: str
    data: dict[str, Any]
    turn_id: str

    def format_sse(self) -> str:
        payload = json.dumps(self.data, ensure_ascii=False, separators=(",", ":"), default=str)
        return f"id: {self.id}\nevent: {self.event}\ndata: {payload}\n\n"


@dataclass
class _TurnChannel:
    next_id: int = 1
    events: deque[StreamEvent] = field(default_factory=lambda: deque(maxlen=_MAX_EVENTS_PER_TURN))
    subscribers: dict[int, tuple[asyncio.AbstractEventLoop, asyncio.Queue[StreamEvent | None]]] = field(
        default_factory=dict
    )
    closed: bool = False
    terminal_at: float | None = None


def safe_stage_for(step: str | None, *, tool_name: str | None = None, default: str = "running") -> str:
    if tool_name and tool_name in _STAGE_MAP:
        return _STAGE_MAP[tool_name]
    if step and step in _STAGE_MAP:
        return _STAGE_MAP[step]
    return default


def safe_tool_name(tool_name: str | None) -> str | None:
    if isinstance(tool_name, str) and tool_name in _SAFE_TOOLS:
        return tool_name
    return None


class TurnEventBus:
    """Thread-safe sync-producer / async-consumer event bus keyed by `turn_id`."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = Lock()
        self._channels: dict[str, _TurnChannel] = {}
        self._next_sub_id = 1

    def _channel(self, turn_id: str) -> _TurnChannel:
        channel = self._channels.get(turn_id)
        if channel is None:
            self._prune_expired_locked()
            channel = _TurnChannel()
            self._channels[turn_id] = channel
        return channel

    def _prune_expired_locked(self) -> None:
        if len(self._channels) < 64:
            return
        now = self._clock()
        stale = [
            tid
            for tid, ch in self._channels.items()
            if ch.closed and not ch.subscribers and ch.terminal_at is not None
            and (now - ch.terminal_at) > _CHANNEL_TTL_SECONDS
        ]
        for tid in stale:
            self._channels.pop(tid, None)

    def publish(
        self,
        turn_id: str,
        event: str,
        data: dict[str, Any],
        *,
        close: bool = False,
    ) -> StreamEvent:
        targets: list[tuple[asyncio.AbstractEventLoop, asyncio.Queue[StreamEvent | None]]] = []
        with self._lock:
            channel = self._channel(turn_id)
            if channel.closed:
                last = channel.events[-1] if channel.events else StreamEvent(
                    id=channel.next_id, event=event, data=dict(data), turn_id=turn_id
                )
                return last
            item = StreamEvent(
                id=channel.next_id,
                event=event,
                data=dict(data),
                turn_id=turn_id,
            )
            channel.next_id += 1
            channel.events.append(item)
            if close:
                channel.closed = True
                channel.terminal_at = self._clock()
            targets = list(channel.subscribers.values())

        for loop, queue in targets:
            try:
                loop.call_soon_threadsafe(queue.put_nowait, item)
                if close:
                    loop.call_soon_threadsafe(queue.put_nowait, None)
            except RuntimeError:
                pass
        return item

    def publish_status(
        self,
        turn_id: str,
        *,
        status: str,
        stopping: bool,
        version: int,
        stage: str | None = None,
    ) -> StreamEvent:
        return self.publish(
            turn_id,
            "turn_status",
            {
                "turn_id": turn_id,
                "status": status,
                "stopping": stopping,
                "version": version,
                "stage": stage or _STAGE_MAP.get(status, status),
            },
        )

    def publish_step_progress(
        self,
        turn_id: str,
        *,
        step: str | None,
        stage: str | None = None,
        status: str = "started",
        tool_name: str | None = None,
        decision_count: int | None = None,
        elapsed_ms: float | None = None,
    ) -> StreamEvent:
        safe_tool = safe_tool_name(tool_name)
        resolved_stage = stage or safe_stage_for(step, tool_name=safe_tool)
        payload: dict[str, Any] = {
            "turn_id": turn_id,
            "step": step if isinstance(step, str) and len(step) <= 64 else resolved_stage,
            "stage": resolved_stage,
            "status": status if status in {"started", "succeeded", "failed"} else "started",
        }
        if safe_tool is not None:
            payload["tool_name"] = safe_tool
        if isinstance(decision_count, int) and decision_count >= 1:
            payload["decision_count"] = decision_count
        if isinstance(elapsed_ms, (int, float)) and math.isfinite(elapsed_ms) and elapsed_ms >= 0:
            payload["elapsed_ms"] = round(float(elapsed_ms), 2)
        return self.publish(turn_id, "step_progress", payload)

    def publish_approved_answer(
        self,
        turn_id: str,
        *,
        message_id: str,
        body: str,
        chunk_size: int = _DEFAULT_CHUNK_SIZE,
    ) -> list[StreamEvent]:
        """Emit answer slices ONLY for an already approved coach answer."""
        events: list[StreamEvent] = []
        size = max(8, int(chunk_size))
        for index, start in enumerate(range(0, len(body), size)):
            delta = body[start : start + size]
            events.append(
                self.publish(
                    turn_id,
                    "answer_delta",
                    {
                        "turn_id": turn_id,
                        "message_id": message_id,
                        "delta": delta,
                        "index": index,
                    },
                )
            )
        return events

    def publish_done(
        self,
        turn_id: str,
        *,
        turn_payload: dict[str, Any],
        message_payload: dict[str, Any] | None,
    ) -> StreamEvent:
        return self.publish(
            turn_id,
            "turn_done",
            {"turn": turn_payload, "message": message_payload},
            close=True,
        )

    def publish_error(
        self,
        turn_id: str,
        *,
        status: str,
        error_code: str | None,
        message: str,
    ) -> StreamEvent:
        return self.publish(
            turn_id,
            "turn_error",
            {
                "turn_id": turn_id,
                "status": status,
                "error_code": error_code,
                "message": message,
            },
            close=True,
        )

    def subscribe(
        self,
        turn_id: str,
        *,
        after_id: int = 0,
    ) -> tuple[list[StreamEvent], asyncio.Queue[StreamEvent | None], bool, Callable[[], None]]:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[StreamEvent | None] = asyncio.Queue()
        with self._lock:
            channel = self._channel(turn_id)
            replay = [ev for ev in channel.events if ev.id > after_id]
            closed = channel.closed
            sub_id = self._next_sub_id
            self._next_sub_id += 1
            if not closed:
                channel.subscribers[sub_id] = (loop, queue)

        def unsubscribe() -> None:
            with self._lock:
                existing = self._channels.get(turn_id)
                if existing is not None:
                    existing.subscribers.pop(sub_id, None)

        return replay, queue, closed, unsubscribe
