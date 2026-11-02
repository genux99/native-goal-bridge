"""Real OS-process contention on one state.db: the insert-only boundary must hold across
separate interpreters (a threaded test shares one connection and cannot prove that)."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

WORKER = Path(__file__).with_name('_create_worker.py')


def test_six_processes_create_exactly_one_goal(sandbox):
    home, _, _ = sandbox
    env = {**os.environ, 'HERMES_HOME': str(home), 'HERMES_AGENT_ROOT': os.environ['HERMES_AGENT_ROOT'],
           'PLUGIN_ROOT': str(Path(__file__).resolve().parents[1]), 'PYTHONPATH': ''}
    procs = [subprocess.Popen([sys.executable, str(WORKER), str(i)], stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True, env=env) for i in range(6)]
    outputs = []
    for proc in procs:
        out, err = proc.communicate(timeout=90)
        assert proc.returncode == 0, err
        outputs.append(json.loads(out.strip().splitlines()[-1]))
    assert sum(1 for o in outputs if o.get('created')) == 1, outputs
    assert sum(1 for o in outputs if o.get('error') == 'goal_exists') == 5, outputs
    from hermes_cli import goals
    state = goals.GoalManager('shared-session').state
    assert state is not None and state.goal.startswith('process ') and state.turns_used == 0
