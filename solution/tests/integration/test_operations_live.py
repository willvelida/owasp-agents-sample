"""Live S4 checks against the running Compose stack (either identity mode):

$env:RUN_INTEGRATION = "1"; uv run pytest tests/integration -q
"""

import os

import pytest
from test_compose_isolation import exec_in

pytestmark = pytest.mark.skipif(os.environ.get("RUN_INTEGRATION") != "1", reason="needs the running Compose stack")

CONTAINER_PROPERTIES = """
import os
from azure.cosmos import CosmosClient
c = CosmosClient(os.environ["COSMOS_ENDPOINT"], credential=os.environ["COSMOS_KEY"], enable_endpoint_discovery=False)
db = c.get_database_client("biotrackr")
for name in ("chat_history", "audit"):
    p = db.get_container_client(name).read()
    print(name, p["partitionKey"]["paths"][0], p.get("defaultTtl"))
"""


def test_history_is_partitioned_by_user_with_a_90_day_ttl_and_audit_exists():
    # WI-09: the emulator stores the TTL but does not expire items, so the configured value is what is checked.
    result = exec_in("chat-api", CONTAINER_PROPERTIES)
    assert "chat_history /userId 7776000" in result.stdout, result.stdout + result.stderr
    assert "audit /chainId" in result.stdout, result.stdout + result.stderr


def test_stored_audit_chains_verify():
    result = exec_in("chat-api", "import runpy; runpy.run_module('chat_api.middleware.audit', run_name='__main__')")
    assert "FAILED" not in result.stdout, result.stdout + result.stderr
    assert result.returncode == 0, result.stdout + result.stderr


def test_kill_switch_is_off_by_default():
    result = exec_in("chat-api", "import os; print(os.environ.get('AGENT_KILL_SWITCH'))")
    assert result.stdout.strip() == "off", result.stdout + result.stderr
