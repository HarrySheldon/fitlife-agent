"""Locally derived admission and end-to-end live batches, with no worker credentials."""
import json
import os
import time
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

from backend.task_evaluation.acceptance import AcceptanceManifest, ActualState, Authorization, admit_live
from backend.task_evaluation.provenance import catalog_digest, fingerprint, source_digest


class LiveConnection(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    reference: str = Field(min_length=1)
    provider: Literal['openai', 'custom']
    protocol: Literal['responses', 'chat_completions']
    model: str = Field(min_length=1)
    base_url: str | None = None
    api_key_env: str = Field(pattern=r'^[A-Z][A-Z0-9_]*API_KEY$')
    review_mode: Literal['off', 'shadow', 'enforce'] = 'enforce'
    grounding_mode: Literal['legacy', 'evidence'] = 'evidence'


def prepare(args):
    """No credentials or Provider objects; compute from source, registered suite and config."""
    from backend.task_evaluation.cli import _git_sha
    from backend.task_evaluation.contracts import Suite
    root = Path(__file__).resolve().parents[2]
    suite_path = Path(args.suite).resolve()
    # Only reviewed repository scenario declarations can be sent outside the machine.
    suite_path.relative_to((root / 'backend/task_evaluation/scenarios').resolve())
    suite = Suite.model_validate_json(suite_path.read_text(encoding='utf-8-sig'))
    if not suite.scenarios:
        raise ValueError('EMPTY_LIVE_SUITE')
    connection = LiveConnection.model_validate_json(Path(args.connection).read_text(encoding='utf-8-sig'))
    common = {'engine': 'unified_coach', 'review_mode': connection.review_mode,
              'grounding_mode': connection.grounding_mode,
              'suite_digest': fingerprint(suite.model_dump(mode='json')),
              'catalog_digest': catalog_digest(),
              'capture_review': args.capture_review,
              'broker_output_cap': 8192,
              'cache_state': args.cache_state}
    treatment = {'strategy': args.strategy, 'repeat': args.repeat, 'phase': args.phase}
    proposal = AcceptanceManifest(
        code_sha=_git_sha(), diff_digest=source_digest(), suite_digest=common['suite_digest'],
        connection_ref=connection.reference, connection_fingerprint=fingerprint(connection.model_dump(mode='json')),
        provider=connection.provider, model=connection.model, protocol=connection.protocol,
        engine='unified_coach', strategy=args.strategy, phase=args.phase,
        invariant_fingerprint=fingerprint(common), treatment_fingerprint=fingerprint(treatment),
        review_mode=connection.review_mode, grounding_mode=connection.grounding_mode,
        synthetic_only=True, repeat=args.repeat, annotation_protocol_version='agent-annotation-v1',
        budget={'max_calls': args.max_calls, 'max_tokens': args.max_tokens, 'max_seconds': args.max_seconds})
    actual = ActualState(**{name: getattr(proposal, name) for name in (
        'code_sha', 'diff_digest', 'suite_digest', 'connection_fingerprint', 'provider', 'model',
        'protocol', 'engine', 'review_mode', 'grounding_mode', 'invariant_fingerprint', 'treatment_fingerprint')},
        scenario_count=len(suite.scenarios), has_real_user_data=False,
        provider_registry=frozenset({'openai', 'custom'}), protocol_registry=frozenset({'responses', 'chat_completions'}),
        engine_registry=frozenset({'unified_coach'}), safety_mode_registry=frozenset({'off','shadow','enforce','legacy','evidence'}),
        max_cases=200)
    return suite, connection, proposal, actual


def production_factory(connection):
    # Called only inside an admitted attempt, in the parent, under cancellation context.
    from backend.domain.model_connection import ModelConnection
    from backend.infrastructure.model_gateway.factory import create_model_gateway
    credential = os.environ.get(connection.api_key_env)
    if not credential:
        raise ValueError('LIVE_CREDENTIAL_UNAVAILABLE')
    return create_model_gateway(ModelConnection(provider=connection.provider, protocol=connection.protocol,
        base_url=connection.base_url, model=connection.model), credential)


def execute(args, *, factory=None):
    from backend.task_evaluation.budget import BatchBudget
    from backend.task_evaluation.runner import run_suite
    from backend.task_evaluation.report import build_report, render_json, render_markdown
    suite, connection, proposal, actual = prepare(args)
    output = Path(args.output)
    if args.prepare_live:
        output.mkdir(parents=True, exist_ok=True)
        (output / 'proposed-manifest.json').write_text(proposal.model_dump_json(indent=2), encoding='utf-8')
        return 0
    manifest = AcceptanceManifest.model_validate_json(Path(args.manifest).read_text(encoding='utf-8-sig'))
    # Bind every CLI option and the connection reference; no silent manifest overrides.
    if manifest != proposal:
        raise ValueError('LIVE_MANIFEST_MISMATCH')
    approval = json.loads(Path(args.authorization).read_text(encoding='utf-8-sig'))
    digest = approval.pop('manifest_digest', None)
    if digest != fingerprint(manifest.model_dump(mode='json')):
        raise ValueError('LIVE_AUTHORIZATION_SCOPE_MISMATCH')
    authorization = Authorization(**approval)
    if not authorization.approved_by.strip() or not authorization.reference.strip():
        raise ValueError('LIVE_AUTHORIZATION_REQUIRED')
    admit_live(manifest, actual=actual, authorization=authorization)
    if args.phase == 'compare' and (args.strategy != 'reference' or len(suite.scenarios) * args.repeat * 2 > actual.max_cases):
        raise ValueError('LIVE_COMPARE_SCOPE_INVALID')
    if args.dry_run:
        print('ADMITTED; dry-run; Provider calls=0')
        return 0
    admitted_factory = factory or (lambda: production_factory(connection))
    def factory():
        # Expiry is checked before each physical call, including review and retry.
        admit_live(manifest, actual=actual, authorization=authorization)
        return admitted_factory()
    budget = BatchBudget(args.max_calls, args.max_tokens)
    deadline = time.monotonic() + args.max_seconds
    live_settings = {'model': connection.model, 'provider': connection.provider,
                     'review_mode': connection.review_mode, 'grounding_mode': connection.grounding_mode,
                     'capture_review': args.capture_review}
    arms = ('reference', 'optimized') if args.phase == 'compare' else (args.strategy,)
    records = {arm: [] for arm in arms}
    interrupted = False
    review_samples = []

    def save():
        if args.capture_review:
            output.mkdir(parents=True, exist_ok=True)
            (output / 'review-cases.json').write_text(json.dumps(review_samples, ensure_ascii=False, indent=2), encoding='utf-8')
        for arm, values in records.items():
            destination = output / arm if len(arms) == 2 else output
            destination.mkdir(parents=True, exist_ok=True)
            report = build_report(values)
            (destination / 'report.json').write_text(render_json(report), encoding='utf-8')
            (destination / 'report.md').write_text(render_markdown(report), encoding='utf-8')
            (destination / 'manifest.json').write_text(json.dumps({
                'suite': str(args.suite), 'mode': 'live', 'strategy': arm,
                'authorization_ref': authorization.reference, 'manifest_digest': digest,
                'ledger': budget.snapshot(), 'partial': interrupted or time.monotonic() >= deadline,
            }, ensure_ascii=False), encoding='utf-8')
    try:
        # Interleave per case/repeat, alternating the first arm to reduce ordering bias.
        for repeat in range(args.repeat):
            for position, scenario in enumerate(suite.scenarios):
                order = arms if (repeat + position) % 2 == 0 else tuple(reversed(arms))
                for arm in order:
                    records[arm].extend(run_suite([scenario], mode='live', deadline=deadline, budget=budget,
                        git_sha=proposal.code_sha, config_fingerprint=proposal.invariant_fingerprint,
                        strategy=arm, cache_state=args.cache_state, repeat_index=repeat,
                        live_factory=factory, live_settings=live_settings,
                        review_sink=review_samples.append if args.capture_review else None))
                    save()  # checkpoint even if a later case is interrupted
                    if records[arm][-1].error_class == 'interrupted':
                        raise KeyboardInterrupt()
    except BaseException:
        interrupted = True
        raise
    finally:
        save()
    return 0 if all(record.success for values in records.values() for record in values) else 1
