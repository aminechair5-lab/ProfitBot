import secrets
from fastapi import Header, HTTPException
from .config import settings


def require_owner(authorization: str | None = Header(default=None)):
    # Fail closed: no default or hard-coded development credential.
    if not settings.owner_api_token:
        raise HTTPException(status_code=503, detail="OWNER_API_TOKEN is not configured on the server")

    # Be tolerant of harmless header whitespace while still requiring the
    # Bearer scheme and an exact, constant-time token comparison.
    parts = (authorization or "").strip().split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="Owner authentication required")

    token = parts[1].strip()
    if not token or not secrets.compare_digest(token, settings.owner_api_token):
        raise HTTPException(status_code=401, detail="Owner authentication required")
    return True
