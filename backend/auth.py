from datetime import datetime, timedelta, timezone
from typing import Annotated, Optional

from fastapi import Depends, Request, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from . import models, schemas
from .api_errors import ApiError
from .config import settings
from .sqlite_db import get_db


ALGORITHM = "HS256"
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=ALGORITHM)


async def get_current_user(request: Request, token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    credentials_exception = ApiError(
        status.HTTP_401_UNAUTHORIZED,
        "auth.invalid_token",
        "登录凭证无效",
        "Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        session_id = payload.get("session_id")
        if not username:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = db.query(models.User).filter(models.User.username == username).first()
    if user is None:
        raise credentials_exception
    if session_id and user.current_session_id and session_id != user.current_session_id:
        raise ApiError(
            status.HTTP_401_UNAUTHORIZED,
            "auth.session_expired_elsewhere",
            "当前账号已在其他位置登录，请重新登录",
            "This account signed in elsewhere. Sign in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    request.state.security_actor = user.username
    return user


async def get_current_active_user(current_user: Annotated[models.User, Depends(get_current_user)]):
    if not current_user.is_active:
        raise ApiError(400, "auth.account_disabled", "账号已被禁用", "The account is disabled")
    return current_user


async def get_current_admin_user(current_user: Annotated[models.User, Depends(get_current_active_user)]):
    if current_user.role not in {"admin", "super_admin"}:
        raise ApiError(403, "auth.permission_denied", "权限不足", "Permission denied")
    return current_user


async def get_current_security_reader(
    current_user: Annotated[models.User, Depends(get_current_active_user)],
):
    if current_user.role not in {"admin", "super_admin", "security_auditor"}:
        raise ApiError(403, "auth.permission_denied", "权限不足", "Permission denied")
    return current_user


async def get_current_security_admin(
    current_user: Annotated[models.User, Depends(get_current_active_user)],
):
    if current_user.role not in {"admin", "super_admin"}:
        raise ApiError(403, "auth.permission_denied", "权限不足", "Permission denied")
    return current_user
