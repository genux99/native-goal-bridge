"""Integrated native gateway test. Model/judge and platform transport are deterministic test doubles.

The production plugin loader, model-tools dispatcher, GoalManager, SQLite store,
post-turn hook, FIFO and adapter drain are real. No API spend or Telegram sends.
"""
import asyncio
import json
from types import SimpleNamespace

import pytest

from test_bridge import CREATE
from gateway.config import Platform, PlatformConfig
from gateway.platforms.base import BasePlatformAdapter
from gateway.platforms.event import MessageEvent, MessageType
from gateway.run_goals import GatewayGoalsMixin
from gateway.run_busy import GatewayBusySessionMixin
from gateway.session import SessionSource, build_session_key


class ProbeAdapter(BasePlatformAdapter):
    def __init__(self):
        super().__init__(PlatformConfig(enabled=True), Platform.TELEGRAM)
        self.sent = []
        self.delivered = asyncio.Event()

    async def connect(self):
        pass

    async def disconnect(self):
        pass

    async def get_chat_info(self, chat_id):
        return {}

    async def send(self, chat_id, content, reply_to=None, metadata=None):
        self.sent.append(content)
        if len(self.sent) == 2:
            self.delivered.set()
        return SimpleNamespace(success=True, message_id=str(len(self.sent)))

    async def send_typing(self, chat_id, metadata=None):
        pass


class NativeHookHarness(GatewayGoalsMixin, GatewayBusySessionMixin):
    def __init__(self, adapter, source):
        self.adapter = adapter
        self.source = source
        self.config = {}
        self.notices = []

    async def _run_in_executor_with_context(self, fn, *args):
        return await asyncio.to_thread(fn, *args)

    async def _defer_goal_status_notice_after_delivery(self, source, msg):
        self.notices.append(msg)

    def _delivery_adapter_for(self, source):
        return self.adapter

    def _session_key_for_source(self, source):
        return build_session_key(source)

    def _synthetic_prompt_event(self, source, prompt):
        return MessageEvent(text=prompt, message_type=MessageType.TEXT, source=source, internal=True)


@pytest.mark.asyncio
async def test_tool_creation_drives_native_next_turn_without_user_message(sandbox, monkeypatch):
    home, _, _ = sandbox
    from hermes_cli import goals
    from model_tools import handle_function_call
    goals._get_session_db()
    verdicts = iter(['continue', 'done'])
    monkeypatch.setattr(goals, 'judge_goal', lambda *a, **k: (next(verdicts), 'deterministic test judge', False, None, False))
    source = SessionSource(platform=Platform.TELEGRAM, chat_id='test-only-chat',
                           user_id='test-only-user', chat_type='group', thread_id='57')
    adapter = ProbeAdapter()
    runner = NativeHookHarness(adapter, source)
    calls = []

    async def handler(event):
        calls.append(event.text)
        if len(calls) == 1:
            result = json.loads(handle_function_call('goal_manage', CREATE, session_id='host-session',
                                                     enabled_toolsets=['messaging']))
            assert result['created']
            (home / 'part-one.txt').write_text('First step verified', encoding='utf-8')
        else:
            assert event.internal
            assert CREATE['objective'] in event.text
            (home / 'part-two.txt').write_text('Second step verified', encoding='utf-8')
        await runner._post_turn_goal_continuation(session_entry=SimpleNamespace(session_id='host-session'),
                                                   source=source, final_response=f'Completed step {len(calls)}')
        return f'Completed step {len(calls)}'

    adapter.set_message_handler(handler)
    event = MessageEvent(text='authorized test task', message_type=MessageType.TEXT, source=source)
    try:
        await adapter._process_message_background(event, build_session_key(source))
        await asyncio.wait_for(adapter.delivered.wait(), timeout=5)
        assert len(calls) == 2 and len(adapter.sent) == 2
        assert (home / 'part-one.txt').is_file() and (home / 'part-two.txt').is_file()
        state = goals.GoalManager('host-session').state
        assert state.status == 'done' and state.turns_used == 2 and state.max_turns == 3
        assert not adapter._pending_messages
    finally:
        await adapter.cancel_background_tasks()


@pytest.mark.asyncio
@pytest.mark.parametrize('control', ['pause', 'clear'])
async def test_native_user_pause_or_clear_prevents_enqueue(sandbox, control):
    _, _, call = sandbox
    from hermes_cli import goals
    assert call(CREATE)['created']
    manager = goals.GoalManager('host-session')
    getattr(manager, control)()
    source = SessionSource(platform=Platform.TELEGRAM, chat_id='test-only-chat', user_id='test-only-user')
    adapter = ProbeAdapter()
    runner = NativeHookHarness(adapter, source)
    await runner._post_turn_goal_continuation(session_entry=SimpleNamespace(session_id='host-session'),
                                               source=source, final_response='Current step ended')
    assert not adapter._pending_messages
    assert goals.GoalManager('host-session').state.turns_used == 0
    assert call(CREATE)['error'] == 'goal_exists'


def test_native_budget_exhaustion_cannot_be_reset(sandbox, monkeypatch):
    _, _, call = sandbox
    from hermes_cli import goals
    assert call(CREATE)['created']
    monkeypatch.setattr(goals, 'judge_goal', lambda *a, **k: ('continue', 'More work needed', False, None, False))
    manager = goals.GoalManager('host-session')
    assert manager.evaluate_after_turn('Step one')['should_continue']
    assert manager.evaluate_after_turn('Step two')['should_continue']
    decision = manager.evaluate_after_turn('Step three')
    assert not decision['should_continue']
    assert manager.state.status == 'paused' and manager.state.turns_used == 3
    assert call(CREATE)['error'] == 'goal_exists'
    assert goals.GoalManager('host-session').state.turns_used == 3


def test_native_user_write_wins_the_precheck_race(sandbox, monkeypatch):
    _, _, call = sandbox
    from hermes_cli import goals
    db = goals._get_session_db()
    original_get = db.get_meta
    fired = []

    def racing_read(key):
        value = original_get(key)
        if key == 'goal:host-session' and not fired:
            fired.append(key)
            # Native user path (/goal set): a real row lands after the plugin's existence check.
            goals.save_goal('host-session', goals.GoalState(goal='A goal just set by the user',
                                                           status='active', max_turns=7))
        return value

    monkeypatch.setattr(db, 'get_meta', racing_read)
    result = call(CREATE)
    assert fired, 'the race window must have been exercised'
    assert result.get('error') == 'goal_exists', result
    state = goals.GoalManager('host-session').state
    assert state.goal == 'A goal just set by the user' and state.max_turns == 7


@pytest.mark.parametrize('args', [None, [], {'action': []}, {'action': {}}, {'action': 1}])
def test_malformed_arguments_fail_closed(sandbox, args):
    _, _, call = sandbox
    assert call(args)['error'] == 'invalid_arguments'
