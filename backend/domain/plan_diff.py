"""Complete deterministic differences, including additions and domain-level settings."""
_MISSING = object()


def plan_differences(base, candidate, readable_domains):
    differences = []
    def visit(domain, path, before, after, context=()):
        node = before if isinstance(before,dict) else after
        if isinstance(node,dict):
            label = node.get('day') or node.get('name')
            if isinstance(label,str):
                context = (*context,label[:200])
        if isinstance(before, dict) and isinstance(after, dict):
            for key in sorted(before.keys() | after.keys()):
                visit(domain, [*path, key], before.get(key, _MISSING), after.get(key, _MISSING), context)
        elif isinstance(before, list) and isinstance(after, list):
            for index in range(max(len(before), len(after))):
                visit(domain, [*path, index], before[index] if index<len(before) else _MISSING,
                      after[index] if index<len(after) else _MISSING, context)
        elif type(before) is not type(after) or before != after:
            differences.append({'domain':domain, 'path':'.'.join(map(str,path)),
                'old_value':None if before is _MISSING else before,
                'new_value':None if after is _MISSING else after,
                'change_kind':'added' if before is _MISSING else 'removed' if after is _MISSING else 'changed',
                'context':list(context),
                'source':'validated_candidate'})
    for domain, root in (('training','workout_plan'),('diet','diet_plan')):
        if domain in readable_domains:
            visit(domain,[root],base.get(root,{}),candidate.get(root,{}))
    return differences
