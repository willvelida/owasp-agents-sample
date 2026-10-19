"""Request headers per target auth mode.

header  starter: sends X-User-Id with the --as user, no token (the ASI03 weakness is server-side).
entra   solution: MSAL device code sign-in as the demo CLI public client, for
        api://BLUEPRINT_APP_ID/access_as_user. The token's oid must be the --as user's.
local   solution offline: token from the stage-only identity simulator.
"""

import base64
import json
import os
import subprocess
from pathlib import Path
from typing import Any

import httpx

CACHE_DIR = Path(os.environ.get("BIOTRACKR_CACHE_DIR", Path.home() / ".biotrackr"))


class AuthError(Exception):
    pass


def load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()
    return values


def settings_for(target: dict[str, Any], base_dir: Path) -> dict[str, str]:
    """Non-secret IDs from the solution .env (written by scripts/provision_agent_id.ps1), overridable by env vars."""
    env_file = (base_dir / target.get("env_file", "../solution/.env")).resolve()
    values = load_env_file(env_file)
    values.update({k: v for k, v in os.environ.items() if k in values or k.endswith(("_APP_ID", "_OID", "_UPN"))})
    return values


def resolve_url(target: dict[str, Any], base_dir: Path) -> str:
    if "url" in target:
        return target["url"]
    key = target["url_from_azd"]
    solution = (base_dir / target.get("azd_cwd", "../solution")).resolve()
    result = subprocess.run(  # noqa: S603
        ["azd", "env", "get-value", key, "--cwd", str(solution)],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip().startswith("http"):
        raise AuthError(f"could not read {key} from the azd environment in {solution}")
    return result.stdout.strip().rstrip("/") + "/"


def headers_for(auth: str, user: str, target: dict[str, Any] | None = None, base_dir: Path | None = None) -> dict:
    if auth == "header":
        return {"X-User-Id": user}
    target, base_dir = target or {}, base_dir or Path.cwd()
    settings = settings_for(target, base_dir)
    if auth == "local":
        token = local_token(target.get("issuer_url", "http://127.0.0.1:8100"), user)
    elif auth == "entra":
        token = entra_token(settings, user)
    else:
        raise AuthError(f"unknown auth mode '{auth}'")
    verify_user(token, settings, user)
    return {"Authorization": f"Bearer {token}"}


def local_token(issuer_url: str, user: str) -> str:
    response = httpx.get(f"{issuer_url.rstrip('/')}/token", params={"user": user}, timeout=10)
    if response.status_code != 200:
        raise AuthError(f"identity simulator refused user '{user}' (HTTP {response.status_code})")
    return response.json()["access_token"]


def entra_token(settings: dict[str, str], user: str) -> str:
    import msal

    try:
        tenant, client_id, blueprint = settings["TENANT_ID"], settings["CLI_APP_ID"], settings["BLUEPRINT_APP_ID"]
    except KeyError as exc:
        raise AuthError(f"missing {exc.args[0]}; run scripts/provision_agent_id.ps1 -WriteDotEnv") from exc
    upn = settings.get(f"{user.upper()}_UPN")
    scopes = [f"api://{blueprint}/access_as_user"]

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / f"msal-{tenant}-{user}.json"
    cache = msal.SerializableTokenCache()
    if cache_file.exists():
        cache.deserialize(cache_file.read_text(encoding="utf-8"))
    app = msal.PublicClientApplication(
        client_id, authority=f"https://login.microsoftonline.com/{tenant}", token_cache=cache
    )

    result = None
    accounts = app.get_accounts(username=upn) if upn else app.get_accounts()
    if accounts:
        result = app.acquire_token_silent(scopes, account=accounts[0])
    if not result:
        flow = app.initiate_device_flow(scopes=scopes)
        if "user_code" not in flow:
            raise AuthError(f"device code flow failed: {flow.get('error_description', flow)}")
        print(f"Sign in as {upn or user}: {flow['message']}", flush=True)
        result = app.acquire_token_by_device_flow(flow)
    if "access_token" not in result:
        raise AuthError(f"sign-in failed: {result.get('error_description', result.get('error'))}")
    if cache.has_state_changed:
        cache_file.write_text(cache.serialize(), encoding="utf-8")
    return result["access_token"]


def claims_of(token: str) -> dict[str, Any]:
    payload = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))


def verify_user(token: str, settings: dict[str, str], user: str) -> None:
    """Refuse to send a token for someone other than --as (validator finding 4)."""
    expected = settings.get(f"{user.upper()}_OID")
    if not expected:
        raise AuthError(f"no {user.upper()}_OID configured; cannot verify the signed-in user")
    actual = claims_of(token).get("oid")
    if actual != expected:
        raise AuthError(f"signed in as oid {actual}, but --as {user} expects {expected}; sign in as the right user")
