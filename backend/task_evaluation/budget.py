"""Conservative, thread-safe reservations shared by all cases in a batch."""
from threading import Lock
from uuid import uuid4
from math import isfinite


class BatchBudget:
    def __init__(self, limit: float, token_limit: int = 200000):
        if not isfinite(limit) or limit < 0 or not isinstance(token_limit, int) or token_limit < 0:
            raise ValueError("Invalid budget")
        self.limit = limit
        self.spent = 0.0
        self.token_limit = token_limit
        self.tokens_spent = 0
        self._held = {}
        self._lock = Lock()
        self._settled = set()

    def reserve(self, upper_bound: float, token_upper_bound: int = 0):
        if not isfinite(upper_bound) or upper_bound <= 0 or not isinstance(token_upper_bound, int) or token_upper_bound < 0:
            raise ValueError("Invalid reservation")
        with self._lock:
            if (self.spent + sum(v[0] for v in self._held.values()) + upper_bound > self.limit
                or self.tokens_spent + sum(v[1] for v in self._held.values()) + token_upper_bound > self.token_limit):
                return None
            identity = uuid4().hex
            self._held[identity] = (upper_bound, token_upper_bound)
            return identity

    def settle(self, reservation: str, usage: float | None, token_usage: int | None = None):
        with self._lock:
            if reservation in self._settled:
                raise ValueError("Reservation already settled")
            upper_bound, token_bound = self._held[reservation]
            if usage is None:
                return  # Unknown usage retains the full reservation.
            if not isfinite(usage) or usage < 0 or usage > upper_bound or (token_usage is not None and (not isinstance(token_usage, int) or not 0 <= token_usage <= token_bound)):
                raise ValueError("Invalid settlement")
            if token_usage is None and token_bound:
                self._held[reservation] = (0, token_bound)
            else:
                del self._held[reservation]
                self.tokens_spent += token_usage or 0
            self.spent += usage
            self._settled.add(reservation)

    def snapshot(self):
        with self._lock:
            return {"spent_calls": self.spent, "spent_tokens": self.tokens_spent,
                    "reserved_calls": sum(v[0] for v in self._held.values()),
                    "reserved_tokens": sum(v[1] for v in self._held.values())}


class RemoteBudget:
    def __init__(self, channel):
        self.channel = channel

    def reserve(self, upper_bound, token_upper_bound=0):
        self.channel.send({"rpc": "reserve", "upper_bound": upper_bound, "token_upper_bound": token_upper_bound})
        result = self.channel.recv()
        if not result["ok"]:
            raise BudgetExceeded()
        return result["reservation"]

    def settle(self, reservation, usage, token_usage=None):
        self.channel.send({"rpc": "settle", "reservation": reservation, "usage": usage, "token_usage": token_usage})
        if not self.channel.recv()["ok"]:
            raise BudgetExceeded()


class BudgetExceeded(Exception):
    pass


class MeteredMockGateway:
    """Each gateway entry reserves independently, including retry/review entries."""
    provider = "mock"
    model = "deterministic-eval-v1"

    def __init__(self, budget, *, unified_decisions=None):
        self.budget = budget
        self.attempts = 0
        self.estimated_tokens = 0
        self.denied = False
        self.failed_attempts = 0
        self.unified_decisions = iter(unified_decisions) if unified_decisions is not None else None

    def _call(self, function, *args, **kwargs):
        # Local mock accounting estimate, never provider-reported usage.
        estimate = max(1, (len(str(args)) + len(str(kwargs)) + 3) // 4) + 1024
        try:
            reservation = self.budget.reserve(1.0, estimate)
        except BudgetExceeded:
            self.denied = True
            raise
        if reservation is None:
            self.denied = True
            raise BudgetExceeded()
        self.attempts += 1
        try:
            result = function(*args, **kwargs)
        except BaseException:
            self.failed_attempts += 1
            self.budget.settle(reservation, None)
            raise
        actual_estimate = max(1, (len(str(args)) + len(str(kwargs)) + len(str(result)) + 3) // 4)
        if actual_estimate > estimate:
            self.failed_attempts += 1
            self.budget.settle(reservation, None)
            self.denied = True
            raise BudgetExceeded()
        self.estimated_tokens += actual_estimate
        self.budget.settle(reservation, 1, actual_estimate)
        return result

    def plan_route(self, question):
        from backend.agent.planner import plan_route
        return self._call(plan_route, question)

    def write_answer(self, state):
        from backend.agent.writer import write_answer
        return self._call(write_answer, state)

    def parse_structured(self, *args, **kwargs):
        from backend.task_evaluation.runner import NetworkAttempt
        def refuse(*args, **kwargs):
            from backend.agent.decision import DecisionEnvelope
            from backend.application.ports.structured_model_gateway import StructuredModelResult
            if self.unified_decisions is not None and kwargs.get('response_model') is DecisionEnvelope:
                value = next(self.unified_decisions, {'kind': 'ask', 'question': '请说明可用器械和训练时间。'})
                output = DecisionEnvelope.model_validate({'decision': value})
                return StructuredModelResult(output, self.model, {})
            raise NetworkAttempt()
        return self._call(refuse, *args, **kwargs)
