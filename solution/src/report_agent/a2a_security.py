"""ASI07: signed, fresh, single-use A2A requests from the chat agent to the report agent.

The S3 token check proves who is calling (app-only token, azp = chat agent, role Report.Generate), but a
captured token works for its whole lifetime with any body. So the chat agent also signs every request with
Ed25519 over the HTTP method, path, a nonce, the issue time, the schema version, and the SHA-256 of the exact
body. After the token check, the report agent rejects a request that is unsigned, signed with an unknown key,
signed over something else (tampered), older than 60 s, or seen before (replayed).

Keys use agentmesh's format (base64 raw Ed25519 public key, kid = "key-" + sha256(public key)[:16]). The private
key is only in chat-api; the report agent holds public keys only. Locally a one-shot Compose service writes the
pair into two volumes (`python -m report_agent.a2a_security keygen`); on Azure the preprovision hook generates it
into the azd environment (`keygen --format env`). The nonce cache is in-process, which is enough while the
report agent runs one replica (as its A2A task store does, WI-21).
"""

import argparse
import base64
import binascii
import hashlib
import logging
import os
import secrets
import sys
import time
from collections import OrderedDict
from collections.abc import Callable, Generator, Iterable
from pathlib import Path
from typing import Literal

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from report_agent.schemas import SCHEMA_VERSION

log = logging.getLogger("report_agent.a2a_security")

SIGNATURE_HEADER = "X-A2A-Signature"
SIGNATURE_VERSION = "a2a-sig/v1"
MAX_AGE_SECONDS = 60
MAX_FUTURE_SKEW_SECONDS = 5
MAX_BODY_BYTES = 64 * 1024
REPLAY_CACHE_ENTRIES = 100_000
PUBLIC_PATHS = frozenset({"/healthz"})

Reason = Literal[
    "missing_signature",
    "malformed_signature",
    "unsupported_version",
    "unsupported_schema",
    "unknown_key",
    "bad_signature",
    "body_mismatch",
    "expired",
    "issued_in_future",
    "replayed",
    "replay_cache_full",
    "body_too_large",
]


class A2ASignatureError(Exception):
    def __init__(self, reason: Reason) -> None:
        super().__init__(reason)
        self.reason: Reason = reason


class SignatureHeader(BaseModel):
    """The versioned signature envelope, sent as `k=v;k=v` in X-A2A-Signature."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    v: Literal["a2a-sig/v1"]
    kid: str = Field(pattern=r"^key-[0-9a-f]{16}$")
    nonce: str = Field(pattern=r"^[A-Za-z0-9_-]{22,64}$")
    iat: int = Field(ge=0)
    sv: str = Field(min_length=1, max_length=64)
    h: str = Field(pattern=r"^[0-9a-f]{64}$")
    sig: str = Field(pattern=r"^[A-Za-z0-9_-]{86}$")

    def encode(self) -> str:
        return ";".join(f"{name}={getattr(self, name)}" for name in type(self).model_fields)

    @classmethod
    def decode(cls, value: str) -> "SignatureHeader":
        fields: dict[str, str] = {}
        for item in value.split(";"):
            name, sep, raw = item.strip().partition("=")
            if not sep or name in fields:
                raise A2ASignatureError("malformed_signature")
            fields[name] = raw
        if fields.get("v") != SIGNATURE_VERSION:
            raise A2ASignatureError("unsupported_version")
        if fields.get("sv") != SCHEMA_VERSION:
            raise A2ASignatureError("unsupported_schema")
        try:
            return cls.model_validate(fields)
        except ValidationError as exc:
            raise A2ASignatureError("malformed_signature") from exc


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def key_id(public_key: Ed25519PublicKey) -> str:
    """agentmesh's verification key id: key- plus the first 16 hex digits of SHA-256 over the raw key."""
    raw = public_key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return f"key-{hashlib.sha256(raw).hexdigest()[:16]}"


def encode_public_key(public_key: Ed25519PublicKey) -> str:
    raw = public_key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(raw).decode()


def encode_private_key(private_key: Ed25519PrivateKey) -> str:
    raw = private_key.private_bytes(
        serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption()
    )
    return base64.b64encode(raw).decode()


def decode_private_key(text: str) -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(base64.b64decode(text.strip(), validate=True))


def decode_public_key(text: str) -> Ed25519PublicKey:
    return Ed25519PublicKey.from_public_bytes(base64.b64decode(text.strip(), validate=True))


def signing_input(method: str, path: str, header: SignatureHeader) -> bytes:
    return "\n".join(
        [header.v, header.kid, header.nonce, str(header.iat), header.sv, header.h, method.upper(), path]
    ).encode()


def sign(
    private_key: Ed25519PrivateKey,
    method: str,
    path: str,
    body: bytes,
    *,
    now: float | None = None,
    nonce: str | None = None,
) -> str:
    unsigned = SignatureHeader.model_construct(
        v=SIGNATURE_VERSION,
        kid=key_id(private_key.public_key()),
        nonce=nonce or secrets.token_urlsafe(24),
        iat=int(time.time() if now is None else now),
        sv=SCHEMA_VERSION,
        h=hashlib.sha256(body).hexdigest(),
        sig="",
    )
    signature = _b64url(private_key.sign(signing_input(method, path, unsigned)))
    return unsigned.model_copy(update={"sig": signature}).encode()


class A2ASigner(httpx.Auth):
    """httpx auth flow: signs each request as it is sent, so every retried poll gets a fresh nonce."""

    requires_request_body = True

    def __init__(self, private_key: Ed25519PrivateKey, clock: Callable[[], float] = time.time) -> None:
        self.private_key = private_key
        self.clock = clock

    def auth_flow(self, request: httpx.Request) -> Generator[httpx.Request, httpx.Response, None]:
        path = request.url.raw_path.split(b"?")[0].decode()
        now = self.clock()
        request.headers[SIGNATURE_HEADER] = sign(self.private_key, request.method, path, request.content, now=now)
        yield request

    @classmethod
    def from_env(cls) -> "A2ASigner | None":
        """The chat agent's signer, or None (report calls then fail closed, nothing unsigned is sent)."""
        text = os.environ.get("A2A_SIGNING_KEY")
        if not text and (path := os.environ.get("A2A_SIGNING_KEY_FILE")):
            try:
                text = Path(path).read_text()
            except OSError as exc:
                log.error("A2A signing key unreadable at %s: %s", path, type(exc).__name__)
                return None
        if not text:
            log.error("no A2A signing key (A2A_SIGNING_KEY or A2A_SIGNING_KEY_FILE); report requests are refused")
            return None
        try:
            return cls(decode_private_key(text))
        except (ValueError, binascii.Error):
            log.error("A2A signing key is not a base64 raw Ed25519 key; report requests are refused")
            return None


class ReplayCache:
    """Nonces seen within the freshness window. Bounded; when full of live nonces it refuses (fail closed)."""

    def __init__(self, max_entries: int = REPLAY_CACHE_ENTRIES) -> None:
        self._seen: OrderedDict[str, float] = OrderedDict()
        self._max = max_entries

    def __len__(self) -> int:
        return len(self._seen)

    def admit(self, key: str, expires_at: float, now: float) -> None:
        # Insertion order is close to expiry order, so expired nonces sit at the front.
        while self._seen and next(iter(self._seen.values())) <= now:
            self._seen.popitem(last=False)
        if key in self._seen:
            raise A2ASignatureError("replayed")
        if len(self._seen) >= self._max:
            raise A2ASignatureError("replay_cache_full")
        self._seen[key] = expires_at


class SignatureVerifier:
    def __init__(
        self,
        public_keys: Iterable[Ed25519PublicKey],
        *,
        clock: Callable[[], float] = time.time,
        cache: ReplayCache | None = None,
        max_age: int = MAX_AGE_SECONDS,
    ) -> None:
        self.keys = {key_id(k): k for k in public_keys}
        if not self.keys:
            raise ValueError("no A2A verification keys")
        self.clock = clock
        self.cache = cache if cache is not None else ReplayCache()
        self.max_age = max_age

    def verify(self, method: str, path: str, body: bytes, header_value: str | None) -> SignatureHeader:
        if not header_value:
            raise A2ASignatureError("missing_signature")
        header = SignatureHeader.decode(header_value)
        if (public_key := self.keys.get(header.kid)) is None:
            raise A2ASignatureError("unknown_key")
        try:
            public_key.verify(_b64url_decode(header.sig), signing_input(method, path, header))
        except (InvalidSignature, ValueError, binascii.Error) as exc:
            raise A2ASignatureError("bad_signature") from exc
        # The signature is genuine; now check that it was made over this body.
        if not secrets.compare_digest(header.h, hashlib.sha256(body).hexdigest()):
            raise A2ASignatureError("body_mismatch")
        now = self.clock()
        if now - header.iat > self.max_age:
            raise A2ASignatureError("expired")
        if header.iat - now > MAX_FUTURE_SKEW_SECONDS:
            raise A2ASignatureError("issued_in_future")
        # Only genuine, fresh requests reach the cache, so forged traffic cannot fill it.
        self.cache.admit(f"{header.kid}:{header.nonce}", header.iat + self.max_age + MAX_FUTURE_SKEW_SECONDS, now)
        return header


def verifier_from_env() -> SignatureVerifier:
    """Fail closed: with no verification key the report agent does not start."""
    text = os.environ.get("A2A_VERIFY_KEYS", "")
    if path := os.environ.get("A2A_VERIFY_KEYS_FILE"):
        try:
            text += "\n" + Path(path).read_text()
        except OSError as exc:
            raise SystemExit(f"A2A verification keys unreadable at {path}: {type(exc).__name__}") from exc
    try:
        keys = [decode_public_key(item) for item in text.replace(",", "\n").split() if item]
        return SignatureVerifier(keys)
    except (ValueError, binascii.Error) as exc:
        raise SystemExit(f"no valid A2A verification key (A2A_VERIFY_KEYS or A2A_VERIFY_KEYS_FILE): {exc}") from exc


class RequireSignedRequest:
    """ASGI middleware, inside the token check: 401 before any A2A handler unless the request is signed and fresh."""

    def __init__(self, app: ASGIApp, verifier: SignatureVerifier) -> None:
        self.app = app
        self.verifier = verifier

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] in PUBLIC_PATHS:
            await self.app(scope, receive, send)
            return
        headers = {k.decode().lower(): v.decode() for k, v in scope["headers"]}
        try:
            body = await _read_body(receive)
            self.verifier.verify(scope["method"], scope["path"], body, headers.get(SIGNATURE_HEADER.lower()))
        except A2ASignatureError as exc:
            log.warning("rejected A2A request: %s", exc.reason)
            # Only callers that passed the token check get here, so the reason is safe to return.
            status = 503 if exc.reason == "replay_cache_full" else 413 if exc.reason == "body_too_large" else 401
            response = JSONResponse({"error": "unauthorized", "reason": exc.reason}, status_code=status)
            await response(scope, receive, send)
            return

        sent = False

        async def replay() -> Message:
            nonlocal sent
            if sent:
                return await receive()
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}

        await self.app(scope, replay, send)


async def _read_body(receive: Receive) -> bytes:
    chunks: list[bytes] = []
    size = 0
    while True:
        message = await receive()
        if message["type"] == "http.disconnect":
            raise A2ASignatureError("malformed_signature")
        chunk = message.get("body", b"")
        size += len(chunk)
        if size > MAX_BODY_BYTES:
            raise A2ASignatureError("body_too_large")
        chunks.append(chunk)
        if not message.get("more_body", False):
            return b"".join(chunks)


def keygen(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="report_agent.a2a_security keygen")
    parser.add_argument("--private", type=Path, help="private key file (created once, mode 0400)")
    parser.add_argument("--public", type=Path, help="public key file (rewritten from the private key)")
    parser.add_argument("--format", choices=["files", "env"], default="files")
    args = parser.parse_args(argv)
    if args.format == "env":
        # For the azd preprovision hook, which stores both values in the azd environment.
        private_key = Ed25519PrivateKey.generate()
        print(f"A2A_SIGNING_KEY={encode_private_key(private_key)}")
        print(f"A2A_VERIFY_KEY={encode_public_key(private_key.public_key())}")
        return 0
    if not args.private or not args.public:
        parser.error("--private and --public are required with --format files")
    if args.private.exists():
        private_key = decode_private_key(args.private.read_text())
    else:
        private_key = Ed25519PrivateKey.generate()
        fd = os.open(args.private, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400)
        with os.fdopen(fd, "w") as handle:
            handle.write(encode_private_key(private_key))
    public = encode_public_key(private_key.public_key())
    tmp = args.public.with_suffix(".tmp")
    tmp.write_text(public + "\n")
    tmp.replace(args.public)
    print(f"A2A signing key {key_id(private_key.public_key())} ready")
    return 0


if __name__ == "__main__":
    if sys.argv[1:2] != ["keygen"]:
        raise SystemExit("usage: python -m report_agent.a2a_security keygen [--private P --public P | --format env]")
    sys.exit(keygen(sys.argv[2:]))
