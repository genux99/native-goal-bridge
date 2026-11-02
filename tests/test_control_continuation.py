"""Native hooks and adapter drain stay real; judge and platform transport are test doubles."""
import asyncio
import json
from types import SimpleNamespace

import pytest

from test_bridge import CREATE
from test_native_gateway import NativeHookHarness, ProbeAdapter
from gateway.config import Platform
from gateway.platforms.event import MessageEvent, MessageType
from gateway.session import SessionSource, build_session_key


@pytest.mark.asyncio
async def test_pause_tool_prevents_native_follow_up(sandbox, monkeypatch):
    _, _, call = sandbox
    from hermes_cli import goals
    from model_tools import handle_function_call
    assert call(CREATE)['created']
    monkeypatch.setattr(goals, 'judge_goal', lambda *a, **k: pytest.fail('paused goal was judged'))
    source = SessionSource(platform=Platform.TELEGRAM, chat_id='test-chat', user_id='test-user')
    adapter = ProbeAdapter()
    runner = NativeHookHarness(adapter, source)
    calls = []

    async def handler(event):
        calls.append(event.text)
        result = json.loads(handle_function_call('goal_manage', {'action': 'pause'}, session_id='host-session'))
        assert result['success'], result
        await runner._post_turn_goal_continuation(session_entry=SimpleNamespace(session_id='host-session'),
                                                  source=source, final_response='Goal paused on request')
        return 'Goal paused on request'

    adapter.set_message_handler(handler)
    try:
        await adapter._process_message_background(MessageEvent(text='Pause', message_type=MessageType.TEXT,
                                                               source=source), build_session_key(source))
        assert len(calls) == 1 and len(adapter.sent) == 1
        assert not adapter._pending_messages
        state = goals.GoalManager('host-session').state
        assert state.status == 'paused' and state.turns_used == 0
    finally:
        await adapter.cancel_background_tasks()


@pytest.mark.asyncio
@pytest.mark.parametrize('action', ['resume', 'update'])
async def test_control_reaches_native_continuation_without_resetting_budget(sandbox, monkeypatch, action):
    _, _, call = sandbox
    from hermes_cli import goals
    from model_tools import handle_function_call
    assert call(CREATE)['created']
    manager = goals.GoalManager('host-session')
    if action == 'resume':
        manager.state.turns_used = 1
        manager.pause()
    initial_turns = manager.state.turns_used
    created_at = manager.state.created_at
    verdicts = iter(['continue', 'done'])
    monkeypatch.setattr(goals, 'judge_goal', lambda *a, **k: (next(verdicts), 'test judge', False, None, False))
    source = SessionSource(platform=Platform.TELEGRAM, chat_id='test-chat', user_id='test-user')
    adapter = ProbeAdapter()
    runner = NativeHookHarness(adapter, source)
    calls = []

    async def handler(event):
        calls.append(event.text)
        if len(calls) == 1:
            args = {'action': action}
            if action == 'update':
                args.update(objective='Revised deliverable', verification='New verification evidence')
            result = json.loads(handle_function_call('goal_manage', args, session_id='host-session'))
            assert result['success'], result
            assert result['goal']['turns_used'] == initial_turns
        else:
            assert event.internal
            if action == 'update':
                assert 'Revised deliverable' in event.text
                assert 'New verification evidence' in event.text
        await runner._post_turn_goal_continuation(session_entry=SimpleNamespace(session_id='host-session'),
                                                  source=source, final_response=f'Checked step {len(calls)}')
        return f'Checked step {len(calls)}'

    adapter.set_message_handler(handler)
    try:
        await adapter._process_message_background(MessageEvent(text='Authorized control test',
                                                               message_type=MessageType.TEXT, source=source),
                                                  build_session_key(source))
        await asyncio.wait_for(adapter.delivered.wait(), timeout=5)
        assert len(calls) == 2 and len(adapter.sent) == 2
        state = goals.GoalManager('host-session').state
        assert state.status == 'done'
        assert state.created_at == created_at and state.turns_used == initial_turns + 2
        assert state.max_turns == 3 and not adapter._pending_messages
    finally:
        await adapter.cancel_background_tasks()
