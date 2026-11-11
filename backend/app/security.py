import secrets
from fastapi import Header, HTTPException
from .config import settings

def require_owner(authorization: str | None = Header(default=None)):
    # Fail closed: no default or hard-coded development credential.
    if not settings.owner_api_token:
        raise HTTPException(status_code=503, detail="OWNER_API_TOKEN is not configured on the server")
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token or not secrets.compare_digest(token, settings.owner_api_token):
        raise HTTPException(status_code=401, detail="Owner authentication required")
    return True
