"""Current-session bridge to Hermes' native Goal loop. No scheduler or prompt hook."""
import json

SCHEMA = {
    'name': 'goal_manage',
    'description': (
        'Manage the current session native Goal: create, status, update, pause, resume. Create only '
        'for bounded user-authorized multi-step work with a deliverable and checkable verification, '
        'not simple questions, indefinite monitoring or waiting for the user. stop_when states when '
        'to pause and ask. Create never replaces an existing record, even paused/done/cleared ones. '
        'Update changes only supplied objective/verification/stop_when fields of an active or paused '
        'goal, preserving its identity, status and budget. Update or resume a user-controlled goal '
        'only on the user\'s instruction; never resume after a user pause on your own. Pause stops '
        'future Goal continuation, not an already running tool. Resume keeps used/max turns and '
        'refuses exhausted budgets or terminal records. No other session, budget reset, automatic '
        'approval or extra permissions are available. Spending, sending, deletion and configuration '
        'changes still require approval. Cancellation remains native /goal clear. After success, '
        'finish the turn normally; the native engine judges and continues. Do not create another loop.'
    ),
    'parameters': {
        'type': 'object',
        'properties': {
            'action': {'type': 'string', 'enum': ['create', 'status', 'update', 'pause', 'resume']},
            'objective': {'type': 'string', 'maxLength': 8000,
                          'description': 'For create/update: the concrete deliverable within the user-authorized scope.'},
            'verification': {'type': 'string', 'maxLength': 8000,
                             'description': 'For create/update: observable evidence required before calling the goal done.'},
            'stop_when': {'type': 'string', 'maxLength': 8000,
                          'description': 'For create/update: stop and ask on missing decisions, permissions, blockers or scope changes.'},
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
    if not isinstance(action, str) or action not in {'create', 'status', 'update', 'pause', 'resume'}:
        return json.dumps({'success': False, 'error': 'invalid_arguments'})
    fields = set(args) - {'action'}
    if ((action == 'create' and fields != {'objective', 'verification', 'stop_when'})
            or (action == 'update' and not fields)
            or (action in {'status', 'pause', 'resume'} and fields)
            or any(not isinstance(args[k], str) or not args[k].strip() or len(args[k]) > 8000
                   for k in fields)):
        return json.dumps({'success': False, 'error': 'invalid_arguments',
                           'message': 'create needs all three text fields; update needs at least one. status/pause/resume accept only action. Supplied text must be non-empty and at most 8000 characters.'})
    try:
        from .bridge import execute
        return json.dumps(execute(args, session_id=session_id.strip()), ensure_ascii=False)
    except (ImportError, AttributeError):
        return json.dumps({'success': False, 'error': 'backend_unavailable',
                           'message': 'This Hermes build does not expose the required native Goal backend.'})


def register(ctx):
    ctx.register_tool(name='goal_manage', toolset='messaging', schema=SCHEMA, handler=handle,
                      description='Current-session native Goal lifecycle bridge', emoji='🎯')
