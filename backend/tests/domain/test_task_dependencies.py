"""A change invalidates its dependents and nothing else."""
import pytest


def test_unknown_upstream_invalidates_its_versioned_dependents():
    from backend.domain.task_dependencies import DependencyKey, Node, plan_recompute
    unknown = DependencyKey('public', 'nutrition', '', '1', '1', '1')
    total = DependencyKey('public', 'total', '1', '1', '1', '1')
    result = plan_recompute((Node('nutrition', unknown), Node('total', total, ('nutrition',))),
                            {'nutrition': unknown, 'total': total})
    assert result.reused == ()
    assert set(result.invalidated) == {'nutrition', 'total'}

from backend.domain.task_dependencies import (
    REASONS,
    DependencyKey,
    Node,
    affected_nodes,
    domain_reuse,
    graph_edges,
    plan_recompute,
)


def key(resource_id, *, scope='public', resource='v1', constraints='c1',
        catalog='cat1', processor='p1'):
    return DependencyKey(scope=scope, resource_id=resource_id, resource_revision=resource,
                         constraints_revision=constraints, catalog_revision=catalog,
                         processor_revision=processor)


def dish(name):
    """The chain one described dish goes through, and the total that reads it."""
    return (
        Node(f'{name}.match', key(f'dish:{name}.match')),
        Node(f'{name}.portion', key(f'dish:{name}.portion'), (f'{name}.match',)),
        Node(f'{name}.nutrition', key(f'dish:{name}.nutrition'), (f'{name}.portion',)),
    )


def meal(*names):
    nutrition = tuple(f'{name}.nutrition' for name in names)
    return dish(names[0]) + tuple(
        item for name in names[1:] for item in dish(name)
    ) + (Node('meal.total', key('meal:total'), nutrition),)


NODES = meal('noodles', 'milk-tea')


def test_a_renamed_dish_invalidates_its_own_chain_and_the_total():
    edges = graph_edges(NODES)
    affected = affected_nodes({'noodles.match'}, edges)

    assert affected == {'noodles.match', 'noodles.portion', 'noodles.nutrition', 'meal.total'}


def test_the_other_dish_is_not_invalidated():
    # 面改粉 does not touch 奶茶. If it did, every edit would recompute the draft.
    affected = affected_nodes({'noodles.match'}, graph_edges(NODES))
    assert not {name for name in affected if name.startswith('milk-tea.')}


def test_a_cycle_still_terminates():
    nodes = (Node('a', key('a'), ('b',)), Node('b', key('b'), ('a',)))
    assert affected_nodes({'a'}, graph_edges(nodes)) == {'a', 'b'}


def test_an_unknown_node_widens_nothing():
    assert affected_nodes({'ghost'}, graph_edges(NODES)) == {'ghost'}


def test_a_key_without_an_authoritative_revision_is_never_reused():
    previous = {node.node_id: node.key for node in NODES}
    blind = tuple(Node(node.node_id, key(node.key.resource_id, catalog=''),
                       node.depends_on) for node in NODES)

    outcome = plan_recompute(blind, previous)

    assert outcome.reused == ()
    assert outcome.reasons['noodles.match'] == 'revision_unknown'
    assert set(outcome.reasons.values()) <= REASONS


def test_an_unchanged_graph_reuses_everything():
    previous = {node.node_id: node.key for node in NODES}
    outcome = plan_recompute(NODES, previous)
    assert outcome.reused == tuple(node.node_id for node in NODES)
    assert outcome.invalidated == outcome.computed == ()
    assert outcome.reasons == {}


def test_a_revision_change_invalidates_everything_downstream():
    previous = {node.node_id: node.key for node in NODES}
    moved = tuple(Node(node.node_id,
                       key(node.key.resource_id, resource='v2') if node.node_id == 'noodles.match'
                       else node.key, node.depends_on)
                  for node in NODES)

    outcome = plan_recompute(moved, previous)

    assert outcome.invalidated == ('noodles.match', 'noodles.portion', 'noodles.nutrition',
                                   'meal.total')
    assert outcome.reasons['noodles.match'] == 'version_changed'
    assert outcome.reasons['meal.total'] == 'upstream_changed'
    assert 'milk-tea.match' in outcome.reused


def test_a_constraint_version_change_recomputes_both_dependent_domains():
    # Two domains read the same constraint snapshot. Moving it must invalidate
    # both, even though neither domain's own bytes changed.
    nodes = (Node('plan:training', key('plan.training')),
             Node('plan:diet', key('plan.diet')))
    previous = {node.node_id: node.key for node in nodes}
    moved = tuple(Node(node.node_id, key(node.key.resource_id, constraints='c2'))
                  for node in nodes)

    outcome = plan_recompute(moved, previous)

    assert outcome.reused == ()
    assert set(outcome.invalidated) == {'plan:training', 'plan:diet'}
    assert set(outcome.reasons.values()) == {'version_changed'}


def test_a_node_without_a_previous_result_is_computed_not_invalidated():
    outcome = plan_recompute(NODES, {'noodles.match': key('dish:noodles.match')})
    assert 'noodles.portion' in outcome.computed
    assert 'noodles.portion' not in outcome.invalidated
    assert outcome.reasons['noodles.portion'] == 'no_previous'


def test_the_record_carries_counts_and_reasons_only():
    previous = {node.node_id: node.key for node in NODES}
    record = plan_recompute(NODES, previous, changed={'noodles.match'}).as_record()
    assert record == {'reused': 3, 'invalidated': 4, 'computed': 0,
                      'reasons': {'explicitly_changed': 1, 'upstream_changed': 3}}
    assert not any('noodles' in str(value) for value in record.values())


@pytest.mark.parametrize('scope', ['', 'owner', 'user:1', 'task:', 'public:1'])
def test_a_scope_must_be_public_or_bound_to_an_owner(scope):
    with pytest.raises(ValueError, match='UNREGISTERED_DEPENDENCY_SCOPE'):
        DependencyKey(scope=scope, resource_id='a', resource_revision='v1',
                      constraints_revision='c1', catalog_revision='cat1',
                      processor_revision='p1')


def test_a_node_cannot_depend_on_itself():
    with pytest.raises(ValueError, match='NODE_CANNOT_DEPEND_ON_ITSELF'):
        Node('a', key('a'), ('a',))


def test_domain_reuse_reuses_an_untouched_domain_whose_bytes_match():
    outcome = domain_reuse({'training': 'd1', 'diet': 'd2'}, {'training': 'd1', 'diet': 'd2'},
                           touched={'diet'})
    assert outcome.reused == ('training',)
    assert outcome.reasons['diet'] == 'explicitly_changed'


def test_domain_reuse_invalidates_an_untouched_domain_whose_bytes_moved():
    outcome = domain_reuse({'training': 'd1'}, {'training': 'd9'}, touched=())
    assert outcome.invalidated == ('training',)
    assert outcome.reasons['training'] == 'version_changed'
