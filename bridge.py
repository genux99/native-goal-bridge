"""Native GoalManager creation with an atomic, insert-only persistence boundary."""
import json
import logging
import sqlite3

from hermes_cli import goals

logger = logging.getLogger(__name__)


class GoalExists(Exception):
    """Another goal (even a terminal record) owns this session's budget."""


class CreateOnlyManager(goals.GoalManager):
    def _save(self):
        db = goals._get_session_db()
        if db is None:
            raise RuntimeError('Goal storage unavailable')
        # A read-then-set check races native user commands and parallel tool calls; insert never overwrites.
        inserted = db._execute_write(lambda conn: conn.execute(
            'INSERT INTO state_meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO NOTHING',
            ('goal:' + self.session_id, self._state.to_json()),
        ).rowcount)
        if not inserted:
            raise GoalExists()
        return self._state


def execute(args, *, session_id):
    from hermes_cli.config import load_config

    try:
        db = goals._get_session_db()
        if db is None:
            return {'success': False, 'error': 'backend_unavailable'}
        if args['action'] == 'status':
            raw = db.get_meta('goal:' + session_id)
            state = goals.GoalState.from_json(raw) if raw else None
            return {'success': True, 'goal': json.loads(state.to_json()) if state else None}
        if args['action'] in {'update', 'pause', 'resume'}:
            from .controls import execute_control
            return execute_control(args, session_id=session_id, db=db)
        raw = db.get_meta('goal:' + session_id)
        if raw is not None:
            return {'success': False, 'error': 'goal_exists',
                    'message': 'This session already has a goal record. Use native /goal controls; no budget was reset.'}
        budget = int(((load_config() or {}).get('goals') or {}).get('max_turns') or goals.DEFAULT_MAX_TURNS)
        if budget <= 0:
            return {'success': False, 'error': 'invalid_budget'}
        manager = CreateOnlyManager(session_id, default_max_turns=budget)
        created_state = manager.set(args['objective'].strip(), contract=goals.GoalContract(
            verification=args['verification'].strip(), stop_when=args['stop_when'].strip(),
            boundaries='Stay within the user-authorized task. Ask before spending, publication, deletion or configuration changes.',
        ))
        manager.refresh()
        if manager.state is None or manager.state.to_json() != created_state.to_json():
            return {'success': False, 'error': 'persistence_unverified'}
        return {'success': True, 'created': True, 'goal': json.loads(manager.state.to_json()),
                'message': 'Native goal stored and read back. Continue this turn normally; the host owns judging and continuation.'}
    except GoalExists:
        return {'success': False, 'error': 'goal_exists', 'message': 'A concurrent goal won; no existing record was changed.'}
    except (sqlite3.Error, RuntimeError, ValueError, TypeError):
        logger.exception('Native goal bridge failed; no success is claimed')
        return {'success': False, 'error': 'storage_error',
                'message': 'Native goal state could not be safely read or created. Inspect host logs; do not retry by resetting it.'}
