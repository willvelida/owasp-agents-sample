"""AST check for generated chart code (ASI05, defence in depth).

The isolated chart runner is the boundary; this check only rejects code that is obviously not a chart
before it is sent there. Anything it cannot parse is rejected.
"""

import ast
from dataclasses import dataclass

MAX_CODE_CHARS = 8000
ALLOWED_IMPORTS = frozenset({"matplotlib", "numpy", "math", "datetime"})
DENIED_NAMES = frozenset(
    {
        "eval",
        "exec",
        "compile",
        "open",
        "__import__",
        "__builtins__",
        "getattr",
        "setattr",
        "delattr",
        "globals",
        "locals",
        "vars",
        "dir",
        "input",
        "breakpoint",
        "memoryview",
        "help",
        "exit",
        "quit",
        "os",
        "sys",
        "subprocess",
        "socket",
        "importlib",
        "builtins",
        "ctypes",
        "pickle",
        "shutil",
        "pathlib",
    }
)
DENIED_ATTRIBUTES = frozenset(
    {
        "environ",
        "system",
        "popen",
        "load",
        "loadtxt",
        "genfromtxt",
        "fromfile",
        "tofile",
        "save",
        "savez",
        "ctypeslib",
        "f2py",
        "rcParams",
        "use",
    }
)


@dataclass(frozen=True)
class CheckResult:
    ok: bool
    reason: str = ""


def check(code: str) -> CheckResult:
    if not isinstance(code, str) or not code.strip():
        return CheckResult(False, "no code")
    if len(code) > MAX_CODE_CHARS:
        return CheckResult(False, f"code longer than {MAX_CODE_CHARS} characters")
    try:
        tree = ast.parse(code, mode="exec")
    except (SyntaxError, ValueError) as exc:
        return CheckResult(False, f"code does not parse: {type(exc).__name__}")
    for node in ast.walk(tree):
        if reason := _violation(node):
            return CheckResult(False, f"line {getattr(node, 'lineno', '?')}: {reason}")
    return CheckResult(True)


def _violation(node: ast.AST) -> str | None:
    if isinstance(node, ast.Import):
        for alias in node.names:
            if alias.name.split(".")[0] not in ALLOWED_IMPORTS:
                return f"import of '{alias.name}' is not allowed"
    elif isinstance(node, ast.ImportFrom):
        if node.level or (node.module or "").split(".")[0] not in ALLOWED_IMPORTS:
            return f"import from '{node.module}' is not allowed"
    elif isinstance(node, ast.Name):
        if node.id in DENIED_NAMES or node.id.startswith("_"):
            return f"name '{node.id}' is not allowed"
    elif isinstance(node, ast.Attribute):
        if node.attr.startswith("_") or node.attr in DENIED_ATTRIBUTES:
            return f"attribute '{node.attr}' is not allowed"
    elif isinstance(node, ast.alias):
        if (node.asname or "").startswith("_"):
            return "private alias is not allowed"
    elif isinstance(node, (ast.Global, ast.Nonlocal, ast.AsyncFunctionDef, ast.Await)):
        return f"{type(node).__name__} is not allowed"
    elif isinstance(node, ast.Constant) and isinstance(node.value, str) and "__" in node.value:
        return "dunder string literal is not allowed"
    return None
