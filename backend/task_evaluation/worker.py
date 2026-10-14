"""Spawn entry point. Application imports occur only after configuration isolation."""
import os
import time
from pathlib import Path


def collect_metrics(root, fixed, gateway, progress):
    from backend.task_evaluation.metrics import runtime_metrics
    from backend.task_evaluation.provenance import fingerprint
    metrics = dict(progress)
    try:
        metrics.update(runtime_metrics(root))
    except Exception:
        pass
    if fixed is not None:
        from backend.safety.gate import SAFETY_RULE_VERSION, default_pack
        metrics.update(rule_version=SAFETY_RULE_VERSION, rule_pack_version=default_pack().pack_version,
            safe_config_fingerprint=fingerprint({"llm_enabled": fixed.llm_enabled,
                "safety_review_mode": fixed.safety_review_mode, "safety_grounding_mode": fixed.safety_grounding_mode}))
    metrics.update(gateway_attempts=gateway.attempts if gateway else None,
        estimated_tokens=None if gateway is None or gateway.failed_attempts else gateway.estimated_tokens,
        known_estimated_tokens=gateway.estimated_tokens if gateway else None,
        failed_attempts=gateway.failed_attempts if gateway else None,
        model=gateway.model if gateway and gateway.attempts else None,
        provider_usage=None, mock_usage_estimated=True, token_measurement="mock_character_estimate")
    return metrics


def worker_main(channel, declaration, temporary):
    gateway = None
    fixed = None
    root = Path(temporary)
    progress = {}
    from backend.task_evaluation.runner import CaseResult, CaseError, NetworkAttempt, execute_scenario
    from backend.task_evaluation.contracts import Scenario
    scenario = Scenario.model_validate(declaration)
    try:
        if True:  # Workspace lifetime belongs to the parent, including forced termination.
            root = Path(temporary)
            from backend.task_evaluation.runner import reject_nonempty_workspace
            reject_nonempty_workspace(root)
            from backend.config import Settings, get_settings
            for key in list(os.environ):
                if key.lower() in Settings.model_fields or any(word in key.upper() for word in ("API_KEY", "SECRET", "TOKEN", "CREDENTIAL")):
                    os.environ.pop(key, None)
            Settings.settings_customise_sources = classmethod(lambda cls, settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings: (init_settings,))
            fixed = Settings(_env_file=None, data_dir=root, sqlite_database_path=root / "fitlife.sqlite3", auth_secret="synthetic-evaluation-only", llm_enabled=False)
            get_settings.cache_clear()
            import backend.config as configuration
            configuration.get_settings = lambda: fixed
            os.environ["DATA_DIR"] = str(root)
            os.environ["SQLITE_DATABASE_PATH"] = str(fixed.database_path)

            from backend.task_evaluation.network import install_network_guard
            install_network_guard()
            from backend.main import create_app
            from backend.agent import graph
            from backend.api import plan, smart_entry
            from backend.task_evaluation.budget import MeteredMockGateway, RemoteBudget
            gateway = MeteredMockGateway(RemoteBudget(channel))
            graph._resolve_gateway = lambda *args, **kwargs: gateway
            plan.resolve_user_model_gateway = lambda *args, **kwargs: gateway
            smart_entry.resolve_user_model_gateway = lambda *args, **kwargs: gateway
            if scenario.initial_state.faults.crash_worker:
                os._exit(23)
            time.sleep(scenario.initial_state.faults.sleep_seconds)
            from fastapi.testclient import TestClient
            from backend.task_evaluation.seeding import seed_environment, UnsupportedSeed
            from backend.task_evaluation.observation import observe_database
            with TestClient(create_app()) as client:
                headers = seed_environment(client, scenario, root)
                def before_step(step):
                    if scenario.initial_state.faults.expire_drafts:
                        import sqlite3
                        with sqlite3.connect(fixed.database_path) as connection:
                            connection.execute("UPDATE record_drafts SET expires_at='2000-01-01T00:00:00Z'")
                result = execute_scenario(scenario, client, headers_factory=lambda actor: headers[actor], observer=lambda: observe_database(fixed.database_path, actors=headers.user_ids, data_dir=root), before_step=before_step, progress_metrics=progress)
                from dataclasses import replace
                from backend.task_evaluation.metrics import runtime_metrics
                from backend.safety.gate import SAFETY_RULE_VERSION, default_pack
                from backend.task_evaluation.provenance import fingerprint
                executed = runtime_metrics(root)
                if result.metrics.get("candidate_ms") is None and result.metrics.get("response_ready_ms") is not None and executed["run_succeeded"]:
                    result = replace(result, metrics={**result.metrics, "candidate_ms": result.metrics["response_ready_ms"], "candidate_reason": "response_ready_non_confirmation", "first_candidate": {"kind": "response_ready", "id": None}, "confirmed_candidate": None})
                result = replace(result, status="budget_exceeded" if gateway.denied else result.status,
                    metrics={**result.metrics, **collect_metrics(root, fixed, gateway, progress), **executed,
                    "rule_version": SAFETY_RULE_VERSION, "rule_pack_version": default_pack().pack_version,
                    "safe_config_fingerprint": fingerprint({"llm_enabled": fixed.llm_enabled,
                        "safety_review_mode": fixed.safety_review_mode, "safety_grounding_mode": fixed.safety_grounding_mode}),
                    "gateway_attempts": gateway.attempts, "estimated_tokens": None if gateway.failed_attempts else gateway.estimated_tokens,
                    "known_estimated_tokens": gateway.estimated_tokens, "failed_attempts": gateway.failed_attempts,
                    "provider_usage": None, "mock_usage_estimated": True,
                    "model": gateway.model if gateway.attempts else None,
                    "token_measurement": "mock_character_estimate"})
            channel.send(result)
    except Exception as error:
        status = "case_error" if isinstance(error, (CaseError, KeyError)) else "worker_error"
        if type(error).__name__ == "UnsupportedSeed":
            status = "unsupported"
        if type(error).__name__ == "BudgetExceeded":
            status = "budget_exceeded"
        channel.send(CaseResult(scenario.id, scenario.version, status, failures=(status,),
            metrics=collect_metrics(root, fixed, gateway, progress)))
    finally:
        channel.close()
