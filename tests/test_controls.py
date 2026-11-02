"""The missing controls must preserve the existing native goal, not call set() again."""
import json
import sqlite3

import pytest


def seed(status='active', used=2, budget=5):
    from hermes_cli import goals
    manager = goals.GoalManager('host-session')
    state = manager.set('Original goal', max_turns=budget, contract=goals.GoalContract(
        outcome='Original outcome', verification='Original verification', constraints='Keep constraints',
        boundaries='Keep boundaries', stop_when='Original stop condition'))
    state.status = status
    state.turns_used = used
    state.subgoals = ['Keep this criterion']
    state.gates = [goals.GoalGate(command='test-only gate; never executed here', attempts=1)]
    manager._save()
    return json.loads(state.to_json())


def stored():
    from hermes_cli import goals
    return json.loads(goals._get_session_db().get_meta('goal:host-session'))


@pytest.mark.parametrize('status', ['active', 'paused'])
def test_update_preserves_status_identity_budget_and_unedited_fields(sandbox, status):
    _, _, call = sandbox
    before = seed(status)
    result = call({'action': 'update', 'objective': ' Revised goal ', 'verification': ' New evidence '})
    assert result['success'], result
    expected = {**before, 'goal': 'Revised goal',
                'contract': {**before['contract'], 'verification': 'New evidence'}}
    assert stored() == expected
    assert result['goal'] == expected


@pytest.mark.parametrize('field', ['objective', 'verification', 'stop_when'])
def test_update_accepts_one_field_without_erasing_other_contract_fields(sandbox, field):
    _, _, call = sandbox
    before = seed()
    assert call({'action': 'update', field: 'New value'})['success']
    expected = json.loads(json.dumps(before))
    if field == 'objective':
        expected['goal'] = 'New value'
    else:
        expected['contract'][field] = 'New value'
    assert stored() == expected


def test_pause_preserves_budget_and_repeat_pause_does_not_write(sandbox, monkeypatch):
    _, _, call = sandbox
    before = seed()
    result = call({'action': 'pause'})
    assert result['success'] and result['goal']['status'] == 'paused'
    after = stored()
    for field in ('created_at', 'turns_used', 'max_turns', 'goal', 'contract', 'subgoals', 'gates'):
        assert after[field] == before[field]
    from hermes_cli import goals
    monkeypatch.setattr(goals._get_session_db(), '_execute_write', lambda _: pytest.fail('repeat pause wrote'))
    assert call({'action': 'pause'})['success']
    assert stored() == after


def test_resume_keeps_consumed_turns_and_uses_native_transition(sandbox):
    _, _, call = sandbox
    before = seed('paused')
    result = call({'action': 'resume'})
    assert result['success'], result
    after = stored()
    assert after['status'] == 'active' and after['paused_reason'] is None
    for field in ('created_at', 'turns_used', 'max_turns', 'goal', 'contract', 'subgoals', 'gates'):
        assert after[field] == before[field]


@pytest.mark.parametrize('used', [5, 6])
def test_resume_refuses_exhausted_budget_without_any_write(sandbox, used):
    _, _, call = sandbox
    before = seed('paused', used=used, budget=5)
    result = call({'action': 'resume'})
    assert not result['success'] and result['error'] == 'budget_exhausted'
    assert stored() == before


@pytest.mark.parametrize('action', ['update', 'pause', 'resume'])
def test_control_missing_goal_does_not_create_one(sandbox, action):
    _, _, call = sandbox
    args = {'action': action, **({'objective': 'Change'} if action == 'update' else {})}
    result = call(args)
    assert not result['success'] and result['error'] == 'no_goal'
    from hermes_cli import goals
    assert goals._get_session_db().get_meta('goal:host-session') is None


@pytest.mark.parametrize('status', ['done', 'cleared'])
@pytest.mark.parametrize('action', ['update', 'pause', 'resume'])
def test_controls_do_not_revive_terminal_records(sandbox, status, action):
    _, _, call = sandbox
    before = seed(status)
    result = call({'action': action, **({'objective': 'Change'} if action == 'update' else {})})
    assert not result['success'] and result['error'] == 'invalid_state'
    assert stored() == before


@pytest.mark.parametrize('args', [
    {'action': 'update'}, {'action': 'update', 'objective': ''},
    {'action': 'update', 'verification': '  '}, {'action': 'update', 'stop_when': False},
    {'action': 'update', 'objective': 'x', 'max_turns': 999},
    {'action': 'pause', 'objective': 'Overwrite'}, {'action': 'resume', 'force': True},
    {'action': 'resume', 'reset_budget': True},
])
def test_controls_reject_missing_blank_or_forbidden_arguments(sandbox, args):
    _, _, call = sandbox
    before = seed()
    result = call(args)
    assert not result['success'] and result['error'] == 'invalid_arguments'
    assert stored() == before


@pytest.mark.parametrize('action', ['update', 'pause', 'resume'])
def test_controls_cannot_select_another_session(sandbox, action):
    _, _, call = sandbox
    before = seed('paused')
    result = call({'action': action, 'session_id': 'victim',
                   **({'objective': 'Change'} if action == 'update' else {})})
    assert not result['success'] and result['error'] == 'invalid_arguments'
    assert stored() == before
    from hermes_cli.goals import GoalManager
    assert GoalManager('victim').state is None


@pytest.mark.parametrize('action', ['update', 'pause', 'resume'])
def test_concurrent_native_change_wins_over_plugin_control(sandbox, monkeypatch, action):
    _, _, call = sandbox
    seed('paused' if action == 'resume' else 'active')
    from hermes_cli import goals
    db = goals._get_session_db()
    original_get = db.get_meta
    fired = []

    def racing_read(key):
        raw = original_get(key)
        if key == 'goal:host-session' and not fired:
            fired.append(True)
            state = goals.GoalState.from_json(raw)
            state.goal = 'A newer user-authorized goal'
            goals.save_goal('host-session', state)
        return raw

    monkeypatch.setattr(db, 'get_meta', racing_read)
    result = call({'action': action, **({'objective': 'Stale edit'} if action == 'update' else {})})
    assert fired, 'race precondition must be true'
    assert not result['success'] and result['error'] == 'goal_changed', result
    assert json.loads(original_get('goal:host-session'))['goal'] == 'A newer user-authorized goal'


@pytest.mark.parametrize('action', ['update', 'pause', 'resume'])
def test_control_storage_failure_never_claims_success(sandbox, monkeypatch, action):
    _, _, call = sandbox
    before = seed('paused' if action == 'resume' else 'active')
    from hermes_cli import goals

    def fail(_):
        raise sqlite3.OperationalError('test-only unavailable store')

    monkeypatch.setattr(goals._get_session_db(), '_execute_write', fail)
    result = call({'action': action, **({'objective': 'Change'} if action == 'update' else {})})
    assert not result['success']
    assert stored() == before


def test_control_readback_mismatch_never_claims_success(sandbox, monkeypatch):
    _, _, call = sandbox
    seed()
    from hermes_cli import goals
    db = goals._get_session_db()
    original = db.get_meta
    reads = []

    def lose_readback(key):
        if key == 'goal:host-session':
            reads.append(key)
            if len(reads) >= 3:
                return None
        return original(key)

    monkeypatch.setattr(db, 'get_meta', lose_readback)
    result = call({'action': 'pause'})
    assert not result['success'] and result['error'] == 'persistence_unverified', result
    assert len(reads) >= 3


@pytest.mark.parametrize('action', ['update', 'pause', 'resume'])
def test_controls_are_profile_scoped(sandbox, tmp_path, action):
    _, _, call = sandbox
    outer = seed()
    from hermes_constants import set_hermes_home_override, reset_hermes_home_override
    from hermes_cli.config import atomic_config_write
    other = tmp_path / 'other-profile'
    other.mkdir()
    atomic_config_write(other / 'config.yaml', {'goals': {'max_turns': 5}})
    token = set_hermes_home_override(other)
    try:
        seed('active' if action == 'pause' else 'paused')
        args = {'action': action, **({'objective': 'Other profile edit'} if action == 'update' else {})}
        result = call(args)
        assert result['success'], result
        assert result['goal']['goal'] == ('Other profile edit' if action == 'update' else 'Original goal')
        assert result['goal']['status'] == ('active' if action == 'resume' else 'paused')
    finally:
        from hermes_state_registry import close_all_under
        close_all_under(other)
        reset_hermes_home_override(token)
    assert stored() == outer
