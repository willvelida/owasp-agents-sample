"""Versioned policy files shared by the chat API and the health MCP server (solution/policies)."""

import hashlib
import os
from pathlib import Path
from typing import Any

import yaml


class PolicyError(Exception):
    """A policy file is missing, malformed, or does not match its pinned hash."""


def policy_dir() -> Path:
    configured = os.environ.get("POLICY_DIR")
    # src/governance/__init__.py -> solution/policies when running from a checkout.
    return Path(configured) if configured else Path(__file__).resolve().parents[2] / "policies"


def read_bytes(name: str, directory: Path | None = None) -> bytes:
    path = (directory or policy_dir()) / name
    try:
        return path.read_bytes()
    except OSError as exc:
        raise PolicyError(f"cannot read policy file {path}: {exc}") from exc


def load_yaml(name: str, directory: Path | None = None) -> dict[str, Any]:
    data = yaml.safe_load(read_bytes(name, directory))
    if not isinstance(data, dict):
        raise PolicyError(f"{name} must contain a mapping")
    return data


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
