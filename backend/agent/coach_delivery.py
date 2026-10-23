"""Final prose is untrusted; numeric blocks are rendered from authorized tools."""
import re
from backend.agent.decision import AskDecision
from backend.agent.safety import review_output
from backend.agent.semantic_review import collect_review, ObservationReviewer
from backend.domain.coach_answer import limits_for_or_default
from backend.domain.errors import configuration_error


def answer_contract(decision, executor, command):
    if not command.coach_action:
        for reference in getattr(decision, 'evidence_refs', []):
            observation = executor.evidence(reference)
            if (observation['tool'] == 'fitness.calculate' and isinstance(observation['data'], dict)
                    and observation['data'].get('kind') == 'suggestion'):
                return 'training_plan_advice'
    return command.coach_action


def project_answer(decision, executor, command):
    executor.check_access()
    if isinstance(decision, AskDecision):
        text = decision.question
    else:
        text = decision.body
        blocks = []
        for reference in decision.evidence_refs:
            observation = executor.evidence(reference)
            data = observation['data']
            if observation['tool'] == 'fitness.calculate' and isinstance(data, dict):
                if data.get('kind') == 'suggestion':
                    blocks.append(data['suggestion_markdown'])
                else:
                    # Fixed numeric metric names come from deterministic algorithms,
                    # never from model-proposed facts or arbitrary record text.
                    blocks.append('\n'.join(f'- {key}: {value}' for key, value in data.items()
                        if key != 'summary' and type(value) in (int, float, bool)))
        for block in blocks:
            if block:
                text = text.replace(block, '')
    # Questions are also publishable content: a question may smuggle in a factual
    # premise. Figures belong in typed evidence blocks, not either prose branch.
    if re.search(r'[0-9０-９%％]|[零一二两三四五六七八九十百千万]+\s*(?:公斤|千克|kg|组|次|秒|分钟|千卡|克)|\b(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|twenty|thirty|forty|fifty|hundred|thousand)(?:[ -]+(?:and|a|hundred|thousand|one|two|three|four|five|six|seven|eight|nine|ten|twenty|thirty))*\s*(?:kg|kilograms?|kilos?|grams?|kcal|calories?|sets?|reps?|minutes?|seconds?|hours?|pounds?)\b', text, re.I):
        raise ValueError('UNVERIFIED_NUMERIC_PROSE')
    if not isinstance(decision, AskDecision):
        text = '\n\n'.join([text.strip(), *dict.fromkeys(block for block in blocks if block)])
    if re.search(r'sk-[A-Za-z0-9_-]{8,}|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}', text):
        raise ValueError('PRIVATE_DATA_IN_OUTPUT')
    if re.search(r'已(?:经)?(?:保存|激活|删除|更新记录)|\b(?:saved|activated|deleted)\s+(?:your|the)\b', text, re.I):
        raise ValueError('UNCONFIRMED_WRITE_CLAIM')
    if re.search(r'<[^>]*>|!\[|\]\(\s*(?:https?://|data:|javascript:)', text, re.I):
        raise ValueError('UNSAFE_OUTPUT_MARKUP')
    limit = limits_for_or_default(answer_contract(decision, executor, command), command.answer_mode or 'brief').body_chars
    if not text.strip() or len(text) > limit:
        raise ValueError('ANSWER_LENGTH_EXCEEDED')
    return text


async def review_delivery(decision, executor, command, context, *, gateway=None, mode='off'):
    text = project_answer(decision, executor, command)
    text, verdict = review_output(command.question, text)
    if mode not in {'off', 'shadow', 'enforce'}:
        raise configuration_error('Invalid review mode')
    if mode != 'off':
        if gateway is None:
            if mode == 'enforce':
                raise configuration_error('Required semantic reviewer unavailable')
        else:
            class AuthorizedReviewGateway:
                model = gateway.model
                def parse_structured(self, **kwargs):
                    executor.check_access()
                    return gateway.parse_structured(**kwargs)
            observation = await collect_review(context, AuthorizedReviewGateway(), mode, command.question, text)
            if mode == 'enforce':
                if observation.status in {'unavailable', 'unsupported'}:
                    from backend.safety.models import SafetyDecision
                    text = ('暂时无法完成必要审核，请稍后重试。' if command.language == 'zh-CN'
                            else 'The required review is unavailable. Please try again later.')
                    verdict = SafetyDecision(outcome='rewrite', risk_category='review_unavailable')
                else:
                    text, verdict = review_output(command.question, text,
                        reviewer=ObservationReviewer(observation, mode))
    context.raise_if_cancelled()
    executor.check_access()
    return text, verdict
