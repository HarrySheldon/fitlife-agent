"""A cache that cannot answer for the wrong owner, version or grant.

Every test drives the injected clock; nothing sleeps. The point of the module is
not speed, it is that a reused result is still the result *this* caller was
allowed to see, computed from *these* inputs.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy

import pytest

from backend.domain.task_dependencies import DependencyKey
from backend.infrastructure.agent_runtime.task_cache import (
    NOT_APPLICABLE,
    PUBLIC_SCOPE,
    TaskResultCache,
    owner_scope,
    task_scope,
)


class Clock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def key(*, scope='task:t1', resource='v1', constraints='c1', catalog='cat1',
        processor='p1', resource_id='plan'):
    return DependencyKey(scope=scope, resource_id=resource_id, resource_revision=resource,
                         constraints_revision=constraints, catalog_revision=catalog,
                         processor_revision=processor)


def allow():
    return frozenset({'training'})


def cache(clock, **kwargs):
    values = {'max_entries': 8, 'ttl_seconds': 60, 'clock': clock}
    values.update(kwargs)
    return TaskResultCache(**values)


def test_a_hit_returns_an_independent_copy():
    clock = Clock()
    store = cache(clock)
    value = {'plan': {'days': ['push']}}
    store.put(key(), value)

    first = store.get(key(), authorize=allow)
    first['plan']['days'].append('pull')

    assert store.get(key(), authorize=allow) == value


def test_a_put_copies_what_it_was_given():
    clock = Clock()
    store = cache(clock)
    value = {'plan': ['a']}
    store.put(key(), value)
    value['plan'].append('b')

    assert store.get(key(), authorize=allow) == {'plan': ['a']}


def test_another_owner_does_not_hit():
    clock = Clock()
    store = cache(clock)
    store.put(key(scope='task:t1'), {'plan': 1})

    assert store.get(key(scope='task:t2'), authorize=allow) is None


def test_a_version_change_misses():
    clock = Clock()
    store = cache(clock)
    store.put(key(resource='v1'), {'plan': 1})

    assert store.get(key(resource='v2'), authorize=allow) is None
    # ... and the old version is still there, because nothing invalidated it.
    assert store.get(key(resource='v1'), authorize=allow) == {'plan': 1}


def test_every_revision_field_participates():
    clock = Clock()
    for field in ('constraints', 'catalog', 'processor'):
        store = cache(clock)
        store.put(key(), {'plan': 1})
        assert store.get(key(**{field: 'moved'}), authorize=allow) is None


def test_a_revoked_grant_refuses_even_a_cached_result():
    clock = Clock()
    store = cache(clock)
    store.put(key(), {'plan': 1})

    def revoked():
        raise PermissionError('SCOPE_ACCESS_REVOKED')

    with pytest.raises(PermissionError, match='SCOPE_ACCESS_REVOKED'):
        store.get(key(), authorize=revoked)


def test_the_check_runs_before_the_lookup_so_a_miss_is_not_a_free_probe():
    clock = Clock()
    store = cache(clock)
    calls = []

    def counted():
        calls.append(1)
        return frozenset()

    assert store.get(key(), authorize=counted) is None
    assert calls == [1]


def test_an_expired_entry_is_a_miss_and_is_dropped():
    clock = Clock()
    store = cache(clock, ttl_seconds=30)
    store.put(key(), {'plan': 1})
    clock.advance(29)
    assert store.get(key(), authorize=allow) == {'plan': 1}

    clock.advance(1)
    assert store.get(key(), authorize=allow) is None
    assert len(store) == 0


def test_a_miss_is_never_stored_as_a_success():
    clock = Clock()
    store = cache(clock)
    with pytest.raises(ValueError, match='CACHE_MUST_NOT_STORE_A_MISS'):
        store.put(key(), None)
    assert len(store) == 0


def test_a_key_without_an_authoritative_revision_is_refused():
    clock = Clock()
    store = cache(clock)
    with pytest.raises(ValueError, match='UNVERSIONED_KEY_MUST_NOT_BE_CACHED'):
        store.put(key(catalog=''), {'plan': 1})


def test_the_fullest_cache_drops_the_oldest_write():
    clock = Clock()
    store = cache(clock, max_entries=2)
    store.put(key(resource='v1'), {'plan': 1})
    clock.advance(1)
    store.put(key(resource='v2'), {'plan': 2})
    clock.advance(1)
    store.put(key(resource='v3'), {'plan': 3})

    assert len(store) == 2
    assert store.get(key(resource='v1'), authorize=allow) is None
    assert store.get(key(resource='v2'), authorize=allow) == {'plan': 2}
    assert store.get(key(resource='v3'), authorize=allow) == {'plan': 3}


def test_rewriting_a_key_refreshes_it_and_keeps_the_bound():
    clock = Clock()
    store = cache(clock, max_entries=2)
    store.put(key(resource='v1'), {'plan': 1})
    store.put(key(resource='v2'), {'plan': 2})
    clock.advance(1)
    store.put(key(resource='v1'), {'plan': 9})
    clock.advance(1)
    store.put(key(resource='v3'), {'plan': 3})

    assert len(store) == 2
    assert store.get(key(resource='v2'), authorize=allow) is None
    assert store.get(key(resource='v1'), authorize=allow) == {'plan': 9}


def test_invalidating_a_scope_leaves_the_others_alone():
    clock = Clock()
    store = cache(clock)
    store.put(key(scope='task:t1'), {'plan': 1})
    store.put(key(scope='task:t2'), {'plan': 2})
    store.put(key(scope='public'), {'plan': 3})

    assert store.invalidate_scope('task:t1') == 1
    assert store.get(key(scope='task:t1'), authorize=allow) is None
    assert store.get(key(scope='task:t2'), authorize=allow) == {'plan': 2}
    assert store.get(key(scope='public'), authorize=allow) == {'plan': 3}


def test_clearing_removes_everything():
    clock = Clock()
    store = cache(clock)
    store.put(key(), {'plan': 1})
    store.clear()
    assert len(store) == 0
    assert store.get(key(), authorize=allow) is None


def test_an_entry_that_is_still_valid_is_not_returned_twice_as_the_same_object():
    clock = Clock()
    store = cache(clock)
    store.put(key(), {'plan': [1]})
    first = store.get(key(), authorize=allow)
    second = store.get(key(), authorize=allow)
    assert first == second and first is not second


def test_the_not_applicable_revision_is_not_the_same_as_unknown():
    # "-" means "this dependency has no such input"; "" means "we do not know".
    assert NOT_APPLICABLE == '-'
    applicable = key(constraints=NOT_APPLICABLE, processor=NOT_APPLICABLE)
    assert applicable.reusable is True
    assert key(constraints='').reusable is False


@pytest.mark.parametrize('field,value', [('max_entries', 0), ('max_entries', -1),
                                         ('ttl_seconds', 0), ('ttl_seconds', -5)])
def test_the_bounds_must_be_positive(field, value):
    with pytest.raises(ValueError):
        cache(Clock(), **{field: value})


def test_a_key_that_is_not_a_dependency_key_is_refused():
    store = cache(Clock())
    with pytest.raises(ValueError, match='CACHE_KEY_MUST_BE_A_DEPENDENCY_KEY'):
        store.put('plan:training', {'plan': 1})


def test_storing_and_reading_does_not_leak_the_stored_object_through_inspection():
    clock = Clock()
    store = cache(clock)
    store.put(key(), {'plan': {'secret': 'x'}})
    snapshot = deepcopy(store.get(key(), authorize=allow))
    snapshot['plan']['secret'] = 'y'
    assert store.get(key(), authorize=allow)['plan']['secret'] == 'x'


# -- the scope rules ---------------------------------------------------


def test_two_owners_cannot_share_a_task_scope():
    # A task id is only unique within an owner, so the owner is part of the scope.
    assert task_scope('alice', 't1') != task_scope('bob', 't1')
    assert task_scope('alice', 't1') == 'task:alice.t1'
    # Both forms are accepted by DependencyKey, which is the only thing that
    # decides whether an entry may be written at all.
    DependencyKey(scope=task_scope('alice', 't1'), resource_id='plan',
                  resource_revision='v1', constraints_revision='c1',
                  catalog_revision='cat1', processor_revision='p1')


def test_a_scope_that_is_not_a_known_identifier_is_refused():
    # An id that carries the separator, a path, a colon or a non-string cannot
    # become a scope: the scope is built from validated parts, never pasted.
    for bad in ('', 'owner:', 'a/b', 'a.b', 'x' * 49, None, 7):
        with pytest.raises(ValueError):
            task_scope(bad, 't1')
        with pytest.raises(ValueError):
            task_scope('alice', bad)
        with pytest.raises(ValueError):
            owner_scope(bad)


def test_the_public_scope_is_shared_on_purpose():
    # A catalogue row is the same row for everyone; only the row's own revision
    # separates one answer from another.
    clock = Clock()
    store = cache(clock)
    store.put(key(scope=PUBLIC_SCOPE), {'food': 'oats'})
    assert store.get(key(scope=PUBLIC_SCOPE), authorize=allow) == {'food': 'oats'}


def test_invalidating_one_owners_task_scope_leaves_the_other_owner():
    clock = Clock()
    store = cache(clock)
    store.put(key(scope=task_scope('alice', 't1')), {'plan': 'a'})
    store.put(key(scope=task_scope('bob', 't1')), {'plan': 'b'})

    assert store.invalidate_scope(task_scope('alice', 't1')) == 1
    assert store.get(key(scope=task_scope('alice', 't1')), authorize=allow) is None
    assert store.get(key(scope=task_scope('bob', 't1')), authorize=allow) == {'plan': 'b'}


# -- producers ---------------------------------------------------------


def test_a_cancelled_producer_never_reaches_the_cache():
    clock = Clock()
    store = cache(clock)

    def cancelled():
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        store.remember(key(), cancelled, authorize=allow)
    assert len(store) == 0


def test_a_producer_that_finds_nothing_stores_nothing():
    clock = Clock()
    store = cache(clock)
    assert store.remember(key(), lambda: None, authorize=allow) is None
    assert len(store) == 0


def test_a_producer_whose_value_cannot_be_copied_leaves_no_entry():
    clock = Clock()
    store = cache(clock)

    class Uncopyable:
        def __deepcopy__(self, memo):
            raise RuntimeError('NOT_COPYABLE')

    with pytest.raises(RuntimeError, match='NOT_COPYABLE'):
        store.remember(key(), Uncopyable, authorize=allow)
    assert len(store) == 0


def test_remembering_checks_the_grant_before_computing():
    clock = Clock()
    store = cache(clock)
    produced = []

    def revoked():
        raise PermissionError('SCOPE_ACCESS_REVOKED')

    with pytest.raises(PermissionError, match='SCOPE_ACCESS_REVOKED'):
        store.remember(key(), lambda: produced.append(1), authorize=revoked)
    assert produced == []

