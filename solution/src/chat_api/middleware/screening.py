"""Prompt-injection screening shared by the input guard and the tool result guard (ASI01).

AGT's PromptInjectionDetector does the detection with its built-in rules plus the versioned patterns
in policies/blocked_patterns.yaml. Before detection the text is normalised (NFKC, invisible format
characters removed), and words that mix Latin with Cyrillic or Greek letters are treated as an
obfuscation attempt, because confusable characters are how filters like this are usually evaded.
"""

import base64
import binascii
import re
import unicodedata
import warnings
from dataclasses import dataclass
from pathlib import Path

from governance import PolicyError, load_yaml

with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    from agent_os.prompt_injection import DetectionConfig, PromptInjectionConfig, PromptInjectionDetector

PATTERNS_FILE = "blocked_patterns.yaml"
_WORD = re.compile(r"\w+", re.UNICODE)
_BASE64 = re.compile(r"[A-Za-z0-9+/]{16,}={0,2}")


@dataclass(frozen=True)
class Verdict:
    blocked: bool
    reason: str = ""


class Screener:
    def __init__(self, detector: PromptInjectionDetector) -> None:
        self._detector = detector

    @classmethod
    def from_policy(cls, directory: Path | None = None) -> "Screener":
        data = load_yaml(PATTERNS_FILE, directory)
        try:
            config = DetectionConfig(
                sensitivity=data.get("sensitivity", "strict"),
                custom_patterns=[re.compile(p, re.IGNORECASE) for p in data.get("custom_patterns", [])],
                blocklist=list(data.get("blocklist", [])),
            )
        except (re.error, ValueError, TypeError) as exc:
            raise PolicyError(f"{PATTERNS_FILE} is invalid: {exc}") from exc
        return cls(PromptInjectionDetector(config, injection_config=PromptInjectionConfig()))

    def screen(self, text: str, *, source: str) -> Verdict:
        normalised = normalise(text)
        if word := mixed_script_word(normalised):
            return Verdict(True, f"mixed-script obfuscation in {source} ({word!r})")
        candidates = {text, normalised, *decoded_segments(normalised)}
        for candidate in candidates:
            result = self._detector.detect(candidate, source=source)
            if result.is_injection:
                kind = result.injection_type.value if result.injection_type else "injection"
                encoded = "" if candidate in (text, normalised) else " (Base64-encoded)"
                return Verdict(True, f"{kind} detected in {source}{encoded}")
        return Verdict(False)


def decoded_segments(text: str) -> list[str]:
    """Readable text hidden in Base64 runs, so encoded instructions meet the same patterns as plain ones."""
    decoded = []
    for match in _BASE64.finditer(text):
        token = match.group(0)
        try:
            plain = base64.b64decode(token + "=" * (-len(token) % 4), validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError):
            continue
        if all(ch.isprintable() or ch.isspace() for ch in plain):
            decoded.append(plain)
    return decoded


def normalise(text: str) -> str:
    folded = unicodedata.normalize("NFKC", text)
    return "".join(ch for ch in folded if unicodedata.category(ch) != "Cf")


def mixed_script_word(text: str) -> str | None:
    for word in _WORD.findall(text):
        scripts = {_script(ch) for ch in word if ch.isalpha()}
        if "LATIN" in scripts and scripts & {"CYRILLIC", "GREEK"}:
            return word
    return None


def _script(ch: str) -> str:
    try:
        return unicodedata.name(ch).split(" ", 1)[0]
    except ValueError:
        return "UNKNOWN"
