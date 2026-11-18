from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.db.models import RevokedToken, User
from app.db.session import get_db
from app.security import get_token_claims, token_hash

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    database: Annotated[Session, Depends(get_db)],
    access_token: Annotated[str | None, Cookie()] = None,
) -> User:
    """Resolve the authenticated user from a signed bearer token."""
    token = credentials.credentials if credentials is not None else access_token
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    claims = get_token_claims(token)
    is_revoked = (
        database.query(RevokedToken)
        .filter(RevokedToken.token_hash == token_hash(token))
        .first()
    )
    user_id = None if claims is None or is_revoked is not None else claims.user_id
    user = database.get(User, user_id) if user_id is not None else None
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid access token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user
