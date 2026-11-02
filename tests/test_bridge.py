import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context

import pytest

CREATE = {'action': 'create', 'objective': 'Produce a checked report',
          'verification': 'Report exists and all cited results are verified.',
          'stop_when': 'Ask before scope changes, spending, publication or needing credentials.'}


def test_discovery_dispatch_and_persistence(sandbox):
    home, manager, call = sandbox
    result = call(CREATE)
    assert result['success'] and result['created']
    assert result['goal']['max_turns'] == 3
    assert result['goal']['turns_used'] == 0
    from hermes_cli.goals import GoalManager
    state = GoalManager('host-session').state
    assert state.goal == CREATE['objective']
    assert state.contract.verification == CREATE['verification']
    assert state.contract.stop_when == CREATE['stop_when']
    with sqlite3.connect(f'file:{(home / "state.db").as_posix()}?mode=ro', uri=True) as db:
        row = db.execute('select value from state_meta where key=?', ('goal:host-session',)).fetchone()
    assert json.loads(row[0])['goal'] == CREATE['objective']


@pytest.mark.parametrize('status', ['active', 'paused', 'done', 'cleared'])
def test_never_replaces_an_existing_record_or_resets_budget(sandbox, status):
    _, _, call = sandbox
    from hermes_cli import goals
    manager = goals.GoalManager('host-session')
    state = manager.set('User-owned goal', max_turns=2)
    state.status = status
    state.turns_used = 2
    manager._save()
    original = goals._get_session_db().get_meta('goal:host-session')
    result = call(CREATE)
    assert not result['success'] and result['error'] == 'goal_exists'
    assert goals._get_session_db().get_meta('goal:host-session') == original


@pytest.mark.parametrize('extra', [{'session_id': 'victim'}, {'max_turns': 1000}, {'force': True}])
def test_model_cannot_choose_another_session_or_budget(sandbox, extra):
    _, _, call = sandbox
    result = call({**CREATE, **extra})
    assert not result['success'] and result['error'] == 'invalid_arguments'
    from hermes_cli.goals import GoalManager
    assert GoalManager('victim').state is None
    assert GoalManager('host-session').state is None


def test_missing_host_binding_fails_closed(sandbox):
    _, _, call = sandbox
    assert call(CREATE, session_id=None)['error'] == 'missing_session'


@pytest.mark.parametrize('action', ['pause', 'resume', 'clear', 'reset', 'gate'])
def test_user_controls_are_not_model_mutations(sandbox, action):
    _, _, call = sandbox
    assert call({'action': action})['error'] == 'invalid_arguments'


@pytest.mark.parametrize('field', ['objective', 'verification', 'stop_when'])
def test_create_requires_actionable_contract(sandbox, field):
    _, _, call = sandbox
    assert call({**CREATE, field: '   '})['error'] == 'invalid_arguments'


def test_status_is_read_only(sandbox):
    _, _, call = sandbox
    from hermes_cli import goals
    assert call({'action': 'status'})['goal'] is None
    assert goals._get_session_db().get_meta('goal:host-session') is None
    assert call(CREATE)['created']
    before = goals._get_session_db().get_meta('goal:host-session')
    assert call({'action': 'status'})['goal']['goal'] == CREATE['objective']
    assert goals._get_session_db().get_meta('goal:host-session') == before


def test_simultaneous_calls_create_only_once(sandbox):
    _, _, call = sandbox
    from hermes_cli import goals
    goals._get_session_db()
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(copy_context().run, call, {**CREATE, 'objective': str(i)}) for i in range(4)]
        results = [f.result(timeout=5) for f in futures]
    assert sum(r.get('created', False) for r in results) == 1
    assert sum(r.get('error') == 'goal_exists' for r in results) == 3


def test_profile_scope_is_not_captured_at_registration(sandbox, tmp_path):
    _, _, call = sandbox
    assert call(CREATE)['created']
    from hermes_constants import set_hermes_home_override, reset_hermes_home_override
    from hermes_cli.config import atomic_config_write
    from hermes_cli.goals import GoalManager
    other = tmp_path / 'other-profile'
    other.mkdir()
    atomic_config_write(other / 'config.yaml', {'goals': {'max_turns': 2}})
    token = set_hermes_home_override(other)
    try:
        result = call({**CREATE, 'objective': 'Other profile task'})
        assert result['created'] and result['goal']['max_turns'] == 2
        assert GoalManager('host-session').state.goal == 'Other profile task'
    finally:
        from hermes_state_registry import close_all_under
        close_all_under(other)
        reset_hermes_home_override(token)
    assert GoalManager('host-session').state.goal == CREATE['objective']


def test_storage_failure_does_not_claim_success(sandbox, monkeypatch):
    _, _, call = sandbox
    from hermes_cli import goals
    db = goals._get_session_db()

    def fail(_callback):
        raise sqlite3.OperationalError('test-only write failure')

    monkeypatch.setattr(db, '_execute_write', fail)
    assert call(CREATE)['success'] is False
    assert db.get_meta('goal:host-session') is None


def test_corrupt_existing_goal_is_never_replaced(sandbox):
    _, _, call = sandbox
    from hermes_cli import goals
    db = goals._get_session_db()
    db.set_meta('goal:host-session', 'not valid json')
    result = call(CREATE)
    assert not result['success']
    assert db.get_meta('goal:host-session') == 'not valid json'
