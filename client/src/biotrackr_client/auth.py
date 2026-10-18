"""Build request headers for a target. Real sign-in arrives in S1."""


def headers_for(auth: str, user: str) -> dict[str, str]:
    if auth == "header":
        return {"X-User-Id": user}
    if auth in {"entra", "local"}:
        raise NotImplementedError(f"auth mode '{auth}' arrives in slice S1")
    raise ValueError(f"unknown auth mode '{auth}'")
