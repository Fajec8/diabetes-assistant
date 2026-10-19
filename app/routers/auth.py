import os
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
)
from fastapi.security import (
    HTTPAuthorizationCredentials,
    HTTPBearer,
)
from jwt import InvalidTokenError
from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.schemas.auth import (
    LoginRequest,
    TokenResponse,
)
from app.schemas.user import UserResponse


router = APIRouter(
    prefix="/auth",
    tags=["Authentication"]
)


password_hash = PasswordHash.recommended()

security = HTTPBearer(
    auto_error=False
)


JWT_SECRET_KEY = os.getenv(
    "JWT_SECRET_KEY"
)

if not JWT_SECRET_KEY:
    raise RuntimeError(
        "JWT_SECRET_KEY environment variable is not set"
    )


JWT_ALGORITHM = "HS256"

ACCESS_TOKEN_EXPIRE_MINUTES = 720


def create_access_token(
    user: User
):
    now = datetime.now(
        timezone.utc
    )

    expires_at = (
        now
        + timedelta(
            minutes=
                ACCESS_TOKEN_EXPIRE_MINUTES
        )
    )

    payload = {
        "sub":
            str(
                user.id
            ),

        "iat":
            now,

        "exp":
            expires_at,

        "type":
            "access"
    }

    return jwt.encode(
        payload,
        JWT_SECRET_KEY,
        algorithm=
            JWT_ALGORITHM
    )


def get_current_user(
    credentials:
        HTTPAuthorizationCredentials
        | None
        = Depends(
            security
        ),

    db: Session = Depends(
        get_db
    )
):
    if credentials is None:
        raise HTTPException(
            status_code=
                status.HTTP_401_UNAUTHORIZED,

            detail=
                "Authentication required",

            headers={
                "WWW-Authenticate":
                    "Bearer"
            }
        )

    token = (
        credentials.credentials
    )

    try:
        payload = jwt.decode(
            token,
            JWT_SECRET_KEY,
            algorithms=[
                JWT_ALGORITHM
            ]
        )

        if (
            payload.get(
                "type"
            )
            != "access"
        ):
            raise InvalidTokenError(
                "Invalid token type"
            )

        subject = payload.get(
            "sub"
        )

        if subject is None:
            raise InvalidTokenError(
                "Missing subject"
            )

        user_id = uuid.UUID(
            subject
        )

    except (
        InvalidTokenError,
        ValueError
    ):
        raise HTTPException(
            status_code=
                status.HTTP_401_UNAUTHORIZED,

            detail=
                "Invalid or expired token",

            headers={
                "WWW-Authenticate":
                    "Bearer"
            }
        )

    user = db.get(
        User,
        user_id
    )

    if user is None:
        raise HTTPException(
            status_code=
                status.HTTP_401_UNAUTHORIZED,

            detail=
                "User not found",

            headers={
                "WWW-Authenticate":
                    "Bearer"
            }
        )

    return user


def ensure_user_access(
    requested_user_id: uuid.UUID,
    current_user: User
):
    if (
        requested_user_id
        != current_user.id
    ):
        raise HTTPException(
            status_code=
                status.HTTP_403_FORBIDDEN,

            detail=(
                "You cannot access data "
                "belonging to another user"
            )
        )


@router.post(
    "/login",
    response_model=
        TokenResponse
)
def login(
    data: LoginRequest,
    db: Session = Depends(
        get_db
    )
):
    user = db.scalar(
        select(
            User
        )
        .where(
            User.email
            == data.email
        )
    )

    if user is None:
        raise HTTPException(
            status_code=
                status.HTTP_401_UNAUTHORIZED,

            detail=
                "Invalid email or password"
        )

    valid_password = (
        password_hash.verify(
            data.password,
            user.password_hash
        )
    )

    if not valid_password:
        raise HTTPException(
            status_code=
                status.HTTP_401_UNAUTHORIZED,

            detail=
                "Invalid email or password"
        )

    token = (
        create_access_token(
            user
        )
    )

    return {
        "access_token":
            token,

        "token_type":
            "bearer",

        "expires_in_seconds":
            ACCESS_TOKEN_EXPIRE_MINUTES
            * 60
    }


@router.get(
    "/me",
    response_model=
        UserResponse
)
def get_me(
    current_user:
        User
        = Depends(
            get_current_user
        )
):
    return current_user