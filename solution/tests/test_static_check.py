"""ASI05 static check corpus (defence in depth; the isolated runner is the boundary)."""

import pytest

from report_agent import static_check

GOOD = """\
import matplotlib.pyplot as plt
import numpy as np
from datetime import date
labels = [p["label"] for p in data]
values = np.array([p["value"] for p in data])
plt.bar(labels, values, color="teal")
plt.title("Daily steps")
caption = f"Average {values.mean():.0f} steps a day."
plt.savefig("chart.png")
"""

ATTACKS = {
    "canary-title": "plt.title(__import__('os').environ['REPORT_AGENT_CANARY'])",
    "import-concat": "m = __import__('o' + 's')\nplt.title(m.getenv('REPORT_AGENT_CANARY'))",
    "getattr-builtins": "f = getattr(__builtins__, '__imp' + 'ort__')\nplt.title(f('os').environ['X'])",
    "mro-walk": "plt.title(str(().__class__.__mro__[1].__subclasses__()))",
    "import-os": "import os\nplt.title(os.environ['REPORT_AGENT_CANARY'])",
    "from-os": "from os import environ\nplt.title(environ['REPORT_AGENT_CANARY'])",
    "import-subprocess": "import subprocess\nsubprocess.run(['id'])",
    "socket": "import socket\nsocket.create_connection(('example.com', 80))",
    "eval": "plt.title(eval('1+1'))",
    "exec": "exec('import os')",
    "compile": "code = compile('1', 'x', 'eval')",
    "open": "plt.title(open('/proc/self/environ').read())",
    "globals": "plt.title(str(globals()))",
    "vars": "plt.title(str(vars()))",
    "numpy-load": "import numpy as np\nnp.load('/etc/passwd', allow_pickle=True)",
    "dunder-string": "plt.title(type(plt).__name__)",
    "dunder-literal": "x = '__globals__'",
    "private-attr": "plt._backend_mod",
    "matplotlib-rcparams": "import matplotlib\nmatplotlib.rcParams['savefig.directory'] = '/'",
    "relative-import": "from . import secrets",
    "sys": "import sys\nplt.title(str(sys.modules))",
    "importlib": "import importlib\nimportlib.import_module('os')",
    "async": "async def f():\n    await g()",
    "syntax-error": "plt.title(",
    "empty": "   ",
    "too-long": "x = 1\n" * 2000,
}


def test_plain_chart_code_passes():
    assert static_check.check(GOOD).ok


@pytest.mark.parametrize("code", ATTACKS.values(), ids=ATTACKS.keys())
def test_attack_corpus_is_rejected(code):
    result = static_check.check(code)
    assert not result.ok
    assert result.reason
