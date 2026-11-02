"""Current-session bridge to Hermes' native Goal loop. No scheduler or prompt hook."""
import json

SCHEMA = {
    'name': 'goal_manage',
    'description': (
        'Create a native standing Goal for this current session, or read its status. Use create only '
        'for a user-authorized multi-step task with a concrete deliverable and checkable acceptance '
        'criteria, when another turn may be needed; not for small questions, open-ended monitoring '
        'or waiting for the user. Write verification as evidence to check, and stop_when as conditions '
        'that require pausing and asking the user. This grants no extra permission: spending, sending, '
        'deletion and configuration changes still need approval. No other session can be selected. '
        'Existing goal records, including paused, done and cleared goals, are never replaced. '
        'The configured native turn budget is fixed; never work around exhaustion by creating again. '
        'Pause, resume and cancellation remain user controls through /goal. After success, finish the '
        'current turn normally; the host judges and schedules continuation. Do not create another loop.'
    ),
    'parameters': {
        'type': 'object',
        'properties': {
            'action': {'type': 'string', 'enum': ['create', 'status']},
            'objective': {'type': 'string', 'maxLength': 8000,
                          'description': 'For create: the concrete deliverable within the user-authorized scope.'},
            'verification': {'type': 'string', 'maxLength': 8000,
                             'description': 'For create: observable evidence required before calling the goal done.'},
            'stop_when': {'type': 'string', 'maxLength': 8000,
                          'description': 'For create: stop and ask on missing decisions, permissions, blockers or scope changes.'},
        },
        'required': ['action'],
        'additionalProperties': False,
    },
}


def handle(args, *, session_id=None, **_context):
    if not isinstance(session_id, str) or not session_id.strip():
        return json.dumps({'success': False, 'error': 'missing_session',
                           'message': 'The host must bind the current session; no ID may be supplied in arguments.'})
    if not isinstance(args, dict) or set(args) - {'action', 'objective', 'verification', 'stop_when'}:
        return json.dumps({'success': False, 'error': 'invalid_arguments'})
    action = args.get('action')
    if not isinstance(action, str) or action not in {'create', 'status'}:
        return json.dumps({'success': False, 'error': 'invalid_arguments'})
    if action == 'create' and any(not isinstance(args.get(k), str) or not args[k].strip()
                                  or len(args[k]) > 8000 for k in ('objective', 'verification', 'stop_when')):
        return json.dumps({'success': False, 'error': 'invalid_arguments',
                           'message': 'create requires non-empty objective, verification and stop_when (up to 8000 characters each).'})
    try:
        from .bridge import execute
        return json.dumps(execute(args, session_id=session_id.strip()), ensure_ascii=False)
    except (ImportError, AttributeError):
        return json.dumps({'success': False, 'error': 'backend_unavailable',
                           'message': 'This Hermes build does not expose the required native Goal backend.'})


def register(ctx):
    ctx.register_tool(name='goal_manage', toolset='messaging', schema=SCHEMA, handler=handle,
                      description='Create-only current-session native Goal bridge', emoji='🎯')
