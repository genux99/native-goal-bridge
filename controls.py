"""Native Goal transitions with compare-and-swap, not a second state machine or scheduler."""
from dataclasses import replace
import json

from hermes_cli import goals


class GoalChanged(RuntimeError):
    """A native/user write superseded this operation's snapshot."""


class ExistingGoalManager(goals.GoalManager):
    def __init__(self, session_id, db, raw):
        super().__init__(session_id)
        self._db = db
        self._expected_raw = raw
        self._state = goals.GoalState.from_json(raw)

    def _save(self):
        changed = self._db._execute_write(lambda conn: conn.execute(
            'UPDATE state_meta SET value = ? WHERE key = ? AND value = ?',
            (self._state.to_json(), 'goal:' + self.session_id, self._expected_raw),
        ).rowcount)
        if not changed:
            raise GoalChanged()
        return self._state


def execute_control(args, *, session_id, db):
    raw = db.get_meta('goal:' + session_id)
    if raw is None:
        return {'success': False, 'error': 'no_goal'}
    manager = ExistingGoalManager(session_id, db, raw)
    state = manager.state
    action = args['action']
    if state is None or state.status not in {'active', 'paused'}:
        return {'success': False, 'error': 'invalid_state',
                'message': 'Controls require an active or paused goal; terminal records are not revived.'}
    if action == 'resume' and state.turns_used >= state.max_turns:
        return {'success': False, 'error': 'budget_exhausted',
                'message': 'Native turn budget exhausted. Ask the user; this tool cannot reset or increase it.'}
    if (action == 'pause' and state.status == 'paused') or (action == 'resume' and state.status == 'active'):
        return {'success': True, 'action': action, 'changed': False, 'goal': json.loads(state.to_json())}
    try:
        if action == 'pause':
            manager.pause(reason='agent-paused')
        elif action == 'resume':
            manager.resume(reset_budget=False)
        else:
            if 'objective' in args:
                state.goal = args['objective'].strip()
            changes = {key: args[key].strip() for key in ('verification', 'stop_when') if key in args}
            manager.set_contract(replace(state.contract, **changes))
    except GoalChanged:
        return {'success': False, 'error': 'goal_changed',
                'message': 'Goal changed concurrently. Read status and reassess; no newer state was overwritten.'}
    expected = state.to_json()
    manager.refresh()
    if manager.state is None or manager.state.to_json() != expected:
        return {'success': False, 'error': 'persistence_unverified'}
    return {'success': True, 'action': action, 'changed': True, 'goal': json.loads(expected),
            'message': 'Native goal state changed and read back; the host owns continuation. Pause does not interrupt a running tool.'}
