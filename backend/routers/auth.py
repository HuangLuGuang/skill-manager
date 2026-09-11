from datetime import datetime, timedelta
import uuid

from fastapi import APIRouter, Depends, Form, Request, status
from sqlalchemy.orm import Session

from .. import auth, models, schemas
from .. import iam
from ..api_errors import ApiError
from ..sqlite_db import get_db
from ..utils.captcha_helper import generate_captcha_image, generate_captcha_text


router = APIRouter(prefix="/auth", tags=["auth"])
CAPTCHA_STORE: dict[str, dict] = {}


@router.get("/captcha")
async def get_captcha():
    captcha_id = str(uuid.uuid4())
    text = generate_captcha_text()
    image = generate_captcha_image(text)
    CAPTCHA_STORE[captcha_id] = {"code": text.lower(), "created_at": datetime.utcnow()}

    now = datetime.utcnow()
    expired = [
        key for key, value in CAPTCHA_STORE.items()
        if (now - value["created_at"]).total_seconds() > 300
    ]
    for key in expired:
        CAPTCHA_STORE.pop(key, None)

    return {"captcha_id": captcha_id, "image": f"data:image/png;base64,{image}"}


@router.post("/register", response_model=schemas.User)
def create_user(user: schemas.UserCreate, request: Request, db: Session = Depends(get_db), actor=Depends(iam.require("users:create"))):
    return iam.create_account(db, request, actor, user.model_dump())


@router.post("/token", response_model=schemas.Token)
def login_for_access_token(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    captcha_id: str = Form(...),
    captcha_code: str = Form(...),
    db: Session = Depends(get_db),
):
    ip = request.client.host if request.client else ""
    request_id = getattr(request.state, "request_id", "") or str(uuid.uuid4())

    def failed_login(reason):
        db.add(models.LoginLog(username=username[:64], ip_address=ip, status=reason, request_id=request_id))
        db.commit()

    if not captcha_id or captcha_id not in CAPTCHA_STORE:
        failed_login("captcha_expired")
        raise ApiError(400, "auth.captcha_expired", "验证码无效或已过期", "The verification code is invalid or expired")
    stored = CAPTCHA_STORE.get(captcha_id)
    if (datetime.utcnow() - stored["created_at"]).total_seconds() > 300:
        CAPTCHA_STORE.pop(captcha_id, None)
        failed_login("captcha_expired")
        raise ApiError(400, "auth.captcha_expired", "验证码无效或已过期", "The verification code is invalid or expired")
    if stored["code"] != captcha_code.lower():
        CAPTCHA_STORE.pop(captcha_id, None)
        failed_login("captcha_incorrect")
        raise ApiError(400, "auth.captcha_incorrect", "验证码错误", "The verification code is incorrect")
    CAPTCHA_STORE.pop(captcha_id, None)

    user = db.query(models.User).filter((models.User.username == username) | (models.User.email == username)).first()
    if not user or not auth.verify_password(password, user.hashed_password):
        failed_login("invalid_credentials")
        raise ApiError(
            status.HTTP_401_UNAUTHORIZED,
            "auth.invalid_credentials",
            "用户名或密码错误",
            "Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        failed_login("account_disabled")
        raise ApiError(400, "auth.account_disabled", "账号已被禁用", "The account is disabled")

    user.last_login_at = datetime.utcnow()
    user.current_session_id = str(uuid.uuid4())
    db.add(models.LoginLog(username=user.username, ip_address=ip, status="success", request_id=request_id))
    db.commit()

    access_token = auth.create_access_token(
        data={"sub": user.username, "session_id": user.current_session_id},
        expires_delta=timedelta(minutes=auth.settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    return {"access_token": access_token, "token_type": "bearer"}


@router.get("/users/me")
async def read_users_me(current_user: models.User = Depends(auth.get_current_user), db: Session = Depends(get_db)):
    return {
        "id": current_user.id,
        "username": current_user.username,
        "email": current_user.email,
        "role": current_user.role,
        "preferred_locale": current_user.preferred_locale,
        "is_active": current_user.is_active,
        "created_at": current_user.created_at,
        "last_login_at": current_user.last_login_at,
        "default_path": iam.access_snapshot(db, current_user)["default_path"],
    }


@router.put("/users/me/locale")
async def update_locale_preference(
    payload: schemas.LocalePreferenceUpdate,
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    current_user.preferred_locale = payload.locale
    db.commit()
    return {"locale": current_user.preferred_locale}


@router.post("/users/me/password")
async def change_password(
    password_data: schemas.PasswordChange,
    request: Request,
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    if not auth.verify_password(password_data.old_password, current_user.hashed_password):
        raise ApiError(
            400,
            "auth.old_password_incorrect",
            "旧密码不正确",
            "The current password is incorrect",
        )
    current_user.hashed_password = auth.get_password_hash(iam.validate_password(password_data.new_password))
    current_user.current_session_id = str(uuid.uuid4())
    iam.audit(db, request, current_user, "auth", "change_password", current_user.id)
    db.commit()
    return {"status": "password updated"}


@router.get("/session-check")
async def check_session(current_user: models.User = Depends(auth.get_current_user)):
    return {"valid": True, "username": current_user.username}
