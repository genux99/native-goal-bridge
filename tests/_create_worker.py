import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.environ['HERMES_AGENT_ROOT'])
sys.path.insert(0, os.environ['PLUGIN_ROOT'])
from bridge import execute  # noqa: E402

print(json.dumps(execute({'action': 'create', 'objective': 'process ' + (sys.argv[1] if len(sys.argv) > 1 else '?'),
                          'verification': 'v', 'stop_when': 's'}, session_id='shared-session')))
