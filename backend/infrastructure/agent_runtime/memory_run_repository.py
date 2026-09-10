from dataclasses import replace
from threading import RLock

from backend.agent.persistence import Checkpoint, InvalidTransition, RunEvent, TERMINAL_STATUSES, next_snapshot, safe_checkpoint, safe_payload


class MemoryRunRepository:
    def __init__(self):
        self._runs = {}
        self._events = {}
        self.lock = RLock()

    def create(self, run):
        with self.lock:
            if run.run_id in self._runs or any(r.request_id == run.request_id for r in self._runs.values()):
                raise InvalidTransition("Run already exists")
            if run.status != "accepted" or run.version != 1:
                raise InvalidTransition("New run must be accepted")
            self._runs[run.run_id] = run
            self._events[run.run_id] = [RunEvent(run.run_id, 1, "RUN_ACCEPTED")]
            return run

    def get(self, run_id, user_id):
        with self.lock:
            run = self._runs.get(run_id)
            if run is None or run.user_id != user_id:
                raise KeyError(run_id)
            return run

    def update(self, run, event_type, payload=None):
        payload = safe_payload(payload or {})
        with self.lock:
            current = self.get(run.run_id, run.user_id)
            updated = next_snapshot(current, run, event_type)
            events = self._events[run.run_id]
            event = RunEvent(run.run_id, len(events) + 1, event_type, run.current_step, run.attempt, payload=payload)
            self._runs[run.run_id] = updated
            events.append(event)
            return updated

    def events(self, run_id, user_id):
        with self.lock:
            self.get(run_id, user_id)
            return tuple(replace(event, payload=dict(event.payload)) for event in self._events[run_id])


class MemoryCheckpointStore:
    def __init__(self, repository):
        self.repository = repository
        self._items = {}

    def save(self, run_id, user_id, name, state):
        state = safe_checkpoint(state)
        with self.repository.lock:
            if self.repository.get(run_id, user_id).status in TERMINAL_STATUSES:
                raise InvalidTransition("Cannot checkpoint a terminal run")
            key = (run_id, name)
            previous = self._items.get(key)
            item = Checkpoint(run_id, name, state, previous.version + 1 if previous else 1)
            self._items[key] = item
            return replace(item, state=dict(item.state))

    def get(self, run_id, user_id, name):
        with self.repository.lock:
            self.repository.get(run_id, user_id)
            item = self._items[(run_id, name)]
            return replace(item, state=dict(item.state))
