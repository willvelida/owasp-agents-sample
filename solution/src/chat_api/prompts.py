"""System prompt for the Biotrackr chat agent.

ASI01: the prompt is a versioned policy file (policies/system_prompt.md) pinned by SHA-256 in
policies/system_prompt.sha256. A missing or modified prompt stops the process at startup with a
non-zero exit code, so the service never becomes ready with an instruction set nobody reviewed.
"""

import hmac
import logging
from pathlib import Path

from governance import PolicyError, read_bytes, sha256_hex

PROMPT_FILE = "system_prompt.md"
HASH_FILE = "system_prompt.sha256"
log = logging.getLogger("chat_api.prompts")


def load_system_prompt(directory: Path | None = None) -> str:
    try:
        prompt = read_bytes(PROMPT_FILE, directory)
        pinned = read_bytes(HASH_FILE, directory).decode().split()[0].lower()
    except (PolicyError, IndexError, UnicodeDecodeError) as exc:
        log.critical("system prompt unavailable: %s", exc)
        raise SystemExit(f"system prompt unavailable: {exc}") from exc
    actual = sha256_hex(prompt)
    if not hmac.compare_digest(actual, pinned):
        log.critical("system prompt hash mismatch: expected %s, got %s", pinned, actual)
        raise SystemExit("system prompt hash mismatch")
    return prompt.decode()
