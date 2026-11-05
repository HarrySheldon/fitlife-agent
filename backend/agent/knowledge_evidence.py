"""Run-local immutable citation identities, bound to authorized observations."""
from copy import deepcopy
import re
from backend.rag.evidence import AnswerReport, EvidenceBlock, EvidenceSet, check_answer
from backend.rag.contracts import content_hash


class KnowledgeEvidence:
    def __init__(self):
        self._snapshots = {}
        self._next = 1

    def bind(self, call_id, items):
        blocks = []
        for item in items:
            value = deepcopy(item)
            # Ignore legacy fixtures without the metadata needed for a real citation.
            if all(value.get(key) for key in ('chunk_id', 'release_id')):
                value['evidence_id'] = f'E{self._next}'
                self._next += 1
                value['content_hash'] = value.get('content_hash') or content_hash(value['text'])
                blocks.append(deepcopy(value))
            else:
                value.pop('evidence_id', None)
            yield value
        self._snapshots[call_id] = tuple(blocks)

    def check(self, text, references, executor):
        blocks = []
        for reference in references:
            executor.check_access()
            known = executor.observations.get(reference)
            if known is None or known.get('status') != 'ok':
                return AnswerReport(False, ('invalid_observation_reference',))
            observation = executor.evidence(reference)  # recheck owner/grants
            if observation['tool'] != 'knowledge.search':
                continue
            expected = self._snapshots.get(reference, ())
            actual = observation['data']
            for item in expected:
                if item not in actual:
                    raise PermissionError('EVIDENCE_SNAPSHOT_CHANGED')
                blocks.append(EvidenceBlock(**{key: item[key] for key in (
                    'evidence_id', 'chunk_id', 'content_hash', 'source', 'heading', 'text')}))
        return check_answer(text, EvidenceSet('ok' if blocks else 'insufficient', None, tuple(blocks)))


def without_citation_ids(text):
    return re.sub(r'\bE\d{1,3}\b', '', text)
