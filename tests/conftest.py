import json
import os
from pathlib import Path
import shutil
import sys

import pytest

CORE = Path(os.environ['HERMES_AGENT_ROOT'])
sys.path.insert(0, str(CORE))
PLUGIN = Path(__file__).resolve().parents[1]


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    from hermes_constants import set_hermes_home_override, reset_hermes_home_override
    home = tmp_path / 'hermes'
    home.mkdir()
    monkeypatch.setenv('HERMES_HOME', str(home))
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    token = set_hermes_home_override(home)
    from hermes_cli import goals
    goals._DB_CACHE.clear()
    from hermes_cli.config import atomic_config_write
    atomic_config_write(home / 'config.yaml', {'plugins': {'enabled': ['native-goal-bridge']},
                                               'goals': {'max_turns': 3}})
    target = home / 'plugins/native-goal-bridge'
    target.mkdir(parents=True)
    for name in ('plugin.yaml', '__init__.py', 'bridge.py'):
        if (PLUGIN / name).exists():
            shutil.copyfile(PLUGIN / name, target / name)
    from hermes_cli.plugins import PluginManager
    manager = PluginManager()
    manager.discover_and_load()
    from tools.registry import registry

    def call(args, session_id='host-session'):
        entry = registry.get_entry('goal_manage', scope=manager.scope_key)
        assert entry is not None, 'plugin must register goal_manage through real discovery'
        raw = registry.dispatch('goal_manage', args, scope=manager.scope_key, session_id=session_id)
        return json.loads(raw) if isinstance(raw, str) else raw

    yield home, manager, call
    manager.unload()
    from hermes_state_registry import close_all_under
    close_all_under(home)
    goals._DB_CACHE.clear()
    reset_hermes_home_override(token)
