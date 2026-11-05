"""Operator handoff: prepare, offline check, explicitly authorized console run."""
import argparse
import csv
import getpass
import json
import os
from pathlib import Path
import time
from uuid import uuid4
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from backend.task_evaluation.cli import parse_args
from backend.task_evaluation.live_batch import LiveConnection, execute, prepare
from backend.task_evaluation.provenance import fingerprint


class Batch(BaseModel):
    model_config = ConfigDict(extra='forbid')
    suite: str
    max_calls: int = Field(gt=0)
    max_tokens: int = Field(gt=0)
    max_seconds: int = Field(gt=0)
    phase: Literal['probe','acceptance'] = 'probe'

    def args(self, directory):
        return parse_args(['--mode','live','--allow-live','--suite',self.suite,
            '--connection',str(directory/'connection.json'), '--manifest',str(directory/'approved-manifest.json'),
            '--authorization',str(directory/'authorization.json'), '--capture-review', '--phase',self.phase,
            '--max-calls',str(self.max_calls), '--max-tokens',str(self.max_tokens),
            '--max-seconds',str(self.max_seconds), '--output',str(directory/'result')])


def prepare_packet(directory, *, connection, batch):
    directory = Path(directory).resolve()
    if directory.exists() and any(directory.iterdir()):
        raise ValueError('BATCH_DIRECTORY_NOT_EMPTY: use a new directory')
    directory.mkdir(parents=True, exist_ok=True)
    (directory/'connection.json').write_text(connection.model_dump_json(indent=2), encoding='utf-8')
    (directory/'batch.json').write_text(batch.model_dump_json(indent=2), encoding='utf-8')
    suite, _, manifest, _ = prepare(batch.args(directory))
    (directory/'approved-manifest.json').write_text(manifest.model_dump_json(indent=2), encoding='utf-8')
    # This is a proposal, not approval: no authorization or credential is created here.
    with (directory/'annotations.csv').open('w', newline='', encoding='utf-8-sig') as handle:
        writer = csv.DictWriter(handle, fieldnames=['case_id','version','annotator','label','secondary','reason'])
        writer.writeheader()
        for case in suite.scenarios:
            writer.writerow({'case_id':case.id,'version':case.version,'label':'unknown'})
    print(f'Prepared (no Provider calls): {directory}')


def check_packet(directory):
    directory = Path(directory).resolve()
    batch = Batch.model_validate_json((directory/'batch.json').read_text(encoding='utf-8-sig'))
    args = batch.args(directory)
    _, _, current, _ = prepare(args)
    from backend.task_evaluation.acceptance import AcceptanceManifest
    approved = AcceptanceManifest.model_validate_json((directory/'approved-manifest.json').read_text(encoding='utf-8-sig'))
    if approved != current:
        raise ValueError('BATCH_CHANGED: prepare a new batch after reviewing changes')
    print(f'CHECK OK; Provider calls=0; limits: {batch.max_calls} calls / {batch.max_tokens} tokens / {batch.max_seconds}s')
    print('Review source questions and approved-manifest.json before running. Prepared files do not authorize calls.')
    return args, approved


def run_packet(directory, *, confirm_live=False, factory=None, read_key=getpass.getpass):
    if not confirm_live:
        raise ValueError('Run requires --confirm-live after reviewing the batch and budget')
    directory = Path(directory).resolve()
    args, manifest = check_packet(directory)
    marker = directory/'run-started.json'
    if marker.exists():
        raise ValueError('BATCH_ALREADY_STARTED: inspect existing results; prepare a new batch to retry')
    connection = LiveConnection.model_validate_json((directory/'connection.json').read_text(encoding='utf-8-sig'))
    original = os.environ.get(connection.api_key_env)
    try:
        if factory is None and not original:
            credential = read_key('API key (hidden, current process only): ')
            if not credential.strip():
                raise ValueError('Empty API key')
            os.environ[connection.api_key_env] = credential
        # Exclusive marker prevents concurrent or accidental repeat spending of one packet.
        with marker.open('x', encoding='utf-8') as handle:
            json.dump({'started_at':time.time()}, handle)
        approval = {'approved_by':'console-operator', 'reference':'console-'+uuid4().hex,
            'expires_at':time.time()+manifest.budget.max_seconds+300,
            'manifest_digest':fingerprint(manifest.model_dump(mode='json'))}
        (directory/'authorization.json').write_text(json.dumps(approval), encoding='utf-8')
        return execute(args, factory=factory)
    finally:
        if original is None:
            os.environ.pop(connection.api_key_env, None)
        else:
            os.environ[connection.api_key_env] = original


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    proposed = sub.add_parser('prepare')
    proposed.add_argument('--batch', required=True)
    proposed.add_argument('--provider', choices=('custom','openai'), default='custom')
    proposed.add_argument('--protocol', choices=('chat_completions','responses'), default='chat_completions')
    proposed.add_argument('--base-url')
    proposed.add_argument('--model', required=True)
    proposed.add_argument('--suite', default='backend/task_evaluation/scenarios/live_probe.json')
    proposed.add_argument('--max-calls', type=int, default=12)
    proposed.add_argument('--max-tokens', type=int, default=250000)
    proposed.add_argument('--max-seconds', type=int, default=180)
    proposed.add_argument('--phase', choices=('probe','acceptance'), default='probe')
    for name in ('check','run'):
        command = sub.add_parser(name)
        command.add_argument('--batch', required=True)
        if name == 'run':
            command.add_argument('--confirm-live', action='store_true')
    args = parser.parse_args(argv)
    try:
        if args.action == 'prepare':
            if args.provider == 'custom' and not args.base_url:
                raise ValueError('Custom provider requires --base-url')
            prepare_packet(args.batch, connection=LiveConnection(reference='operator-evaluation',
                provider=args.provider, protocol=args.protocol, base_url=args.base_url, model=args.model,
                api_key_env='FITLIFE_EVAL_API_KEY'), batch=Batch(suite=args.suite,
                max_calls=args.max_calls,max_tokens=args.max_tokens,max_seconds=args.max_seconds,phase=args.phase))
            return 0
        if args.action == 'check':
            check_packet(args.batch)
            return 0
        return run_packet(args.batch, confirm_live=args.confirm_live)
    except KeyboardInterrupt:
        print('Interrupted; inspect result/report.json and the batch marker before preparing a new batch.')
        return 130
    except (ValueError, OSError):
        print('Batch refused. Check paths, unchanged source/configuration, positive budgets and --confirm-live; use a new batch directory for retries.')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
