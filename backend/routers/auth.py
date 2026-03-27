from datetime import datetime, timedelta
import uuid

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from sqlalchemy.orm import Session

from .. import auth, models, schemas
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
def create_user(user: schemas.UserCreate, db: Session = Depends(get_db)):
    exists = db.query(models.User).filter(models.User.username == user.username).first()
    if exists:
        raise HTTPException(status_code=400, detail="Username already registered")
    db_user = models.User(
        username=user.username,
        email=user.email,
        hashed_password=auth.get_password_hash(user.password),
        role=user.role,
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user


@router.post("/token", response_model=schemas.Token)
def login_for_access_token(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    captcha_id: str = Form(...),
    captcha_code: str = Form(...),
    db: Session = Depends(get_db),
):
    forwarded = request.headers.get("x-forwarded-for")
    ip = forwarded.split(",")[0] if forwarded else request.client.host

    if not captcha_id or captcha_id not in CAPTCHA_STORE:
        raise HTTPException(status_code=400, detail="验证码无效或已过期")
    stored = CAPTCHA_STORE.get(captcha_id)
    if stored["code"] != captcha_code.lower():
        CAPTCHA_STORE.pop(captcha_id, None)
        raise HTTPException(status_code=400, detail="验证码错误")
    CAPTCHA_STORE.pop(captcha_id, None)

    user = db.query(models.User).filter((models.User.username == username) | (models.User.email == username)).first()
    if not user or not auth.verify_password(password, user.hashed_password):
        db.add(models.LoginLog(username=username, ip_address=ip, status="Failed"))
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        db.add(models.LoginLog(username=user.username, ip_address=ip, status="Failed (Disabled)"))
        db.commit()
        raise HTTPException(status_code=400, detail="账号已被禁用")

    user.last_login_at = datetime.utcnow()
    user.current_session_id = str(uuid.uuid4())
    db.add(models.LoginLog(username=user.username, ip_address=ip, status="Success"))
    db.commit()

    access_token = auth.create_access_token(
        data={"sub": user.username, "session_id": user.current_session_id},
        expires_delta=timedelta(minutes=auth.settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    return {"access_token": access_token, "token_type": "bearer"}


@router.get("/users/me")
async def read_users_me(current_user: models.User = Depends(auth.get_current_user)):
    return {
        "id": current_user.id,
        "username": current_user.username,
        "email": current_user.email,
        "role": current_user.role,
        "is_active": current_user.is_active,
        "created_at": current_user.created_at,
        "last_login_at": current_user.last_login_at,
        "default_path": "/config/log-parse",
    }


@router.post("/users/me/password")
async def change_password(
    password_data: schemas.PasswordChange,
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    if not auth.verify_password(password_data.old_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="Incorrect old password")
    current_user.hashed_password = auth.get_password_hash(password_data.new_password)
    db.add(
        models.OperationLog(
            username=current_user.username,
            action="修改密码",
            target=f"用户: {current_user.username}",
            details="用户修改密码",
        )
    )
    db.commit()
    return {"status": "password updated"}


@router.get("/session-check")
async def check_session(current_user: models.User = Depends(auth.get_current_user)):
    return {"valid": True, "username": current_user.username}
