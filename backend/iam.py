"""Role authorization and account lifecycle services."""
import json
import uuid
from datetime import datetime

from fastapi import Depends, Request
from pydantic import ValidationError
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import iam_models as im, models
from .api_errors import ApiError
from .iam_catalog import PAGE_FEATURES, PAGE_PERMISSIONS, PAGES, PERMISSIONS, SYSTEM_ROLES
from .sqlite_db import get_db


def fail(code, zh, en, status=400, **params):
    raise ApiError(status, f"iam.{code}", zh, en, params=params)


def initialize(db):
    db.query(im.RolePermission).filter(im.RolePermission.permission_code.notin_(PERMISSIONS)).delete(synchronize_session=False)
    db.query(im.Permission).filter(im.Permission.code.notin_(PERMISSIONS)).delete(synchronize_session=False)
    for code in sorted(PERMISSIONS):
        if db.get(im.Permission, code) is None:
            module, action = code.split(":")
            db.add(im.Permission(code=code, module=module, action=action))
    db.flush()
    for name, (label, path, codes) in SYSTEM_ROLES.items():
        role = db.get(im.Role, name)
        if role is None:
            db.add(im.Role(name=name, display_name=label, display_key=f"iam.roleNames.{name}", default_path=path, is_system=True))
            db.flush()
            db.add_all(im.RolePermission(role_name=name, permission_code=code) for code in sorted(codes))
        elif role.is_system and role.display_key is None and role.display_name == label:
            role.display_key = f"iam.roleNames.{name}"
        if role is not None and name in {"admin", "super_admin"}:
            existing = set(db.scalars(select(im.RolePermission.permission_code).where(im.RolePermission.role_name == name)))
            db.add_all(im.RolePermission(role_name=name, permission_code=code) for code in sorted(codes - existing))
    # Preserve existing custom role names without inventing privileges.
    for (name,) in db.query(models.User.role).distinct():
        if db.get(im.Role, name) is None:
            db.add(im.Role(name=name, display_name=name, default_path=""))
    for index, (name, parent, zh, en, path, _, icon, _) in enumerate(PAGES):
        if db.get(im.Menu, name) is None:
            db.add(im.Menu(name=name, parent_name=parent, title_zh=zh, title_en=en,
                           title_key=f"iam.navigation.{name}", path=path, icon=icon, sort_order=index, is_system=True))
            db.flush()
    prompt_menu = db.get(im.Menu, 'prompt-guard')
    if (prompt_menu and prompt_menu.is_system
            and prompt_menu.title_zh == 'Prompt 防护测试' and prompt_menu.title_en == 'Prompt Guard Test'):
        prompt_menu.title_zh = 'Prompt 防护'
        prompt_menu.title_en = 'Prompt Guard'
        prompt_menu.title_key = 'iam.navigation.prompt-guard'
    audit_menu = db.get(im.Menu, 'skill-audit')
    if (audit_menu and audit_menu.is_system and audit_menu.title_key is None
            and audit_menu.title_zh == '审计追踪' and audit_menu.title_en == 'Skill Audit'):
        audit_menu.title_key = 'iam.navigation.skill-audit'
        audit_menu.title_en = 'Audit Trail'
    user_stats_menu = db.get(im.Menu, 'user-stats')
    if user_stats_menu and user_stats_menu.is_system:
        user_stats_menu.is_active = False
    stats_menu = db.get(im.Menu, 'stats')
    if (stats_menu and stats_menu.is_system and stats_menu.title_zh == 'Token 压缩统计'
            and stats_menu.title_en == 'Token Compression'):
        stats_menu.title_zh = '用量统计'
        stats_menu.title_en = 'Usage Analytics'
        stats_menu.title_key = 'iam.navigation.stats'
    db.commit()


def migrate(engine):
    for table, field in (("iam_roles", "display_key"), ("iam_menus", "title_key")):
        if field not in {column["name"] for column in inspect(engine).get_columns(table)}:
            with engine.begin() as conn:
                conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {field} VARCHAR(128)")
    if "request_id" not in {column["name"] for column in inspect(engine).get_columns("login_logs")}:
        with engine.begin() as conn:
            conn.exec_driver_sql("ALTER TABLE login_logs ADD COLUMN request_id VARCHAR(64) NOT NULL DEFAULT ''")


def permission_codes(db, user):
    if not user.is_active:
        return set()
    if user.role == "super_admin":
        return set(PERMISSIONS)
    return set(db.scalars(select(im.RolePermission.permission_code).where(im.RolePermission.role_name == user.role)))


def check(db, user, code):
    if code in {"privacy_audit:raw", "traces:raw"} and user.role not in {"admin", "super_admin", "privacy_auditor"}:
        fail("sensitive_role", "原始隐私数据仅允许管理员或隐私审计员访问", "Original private data is restricted to administrators and privacy auditors", 403)
    if code not in permission_codes(db, user):
        fail("permission_denied", "没有此操作权限", "You do not have permission for this action", 403, permission=code)


def require(code):
    from .auth import get_current_active_user

    async def dependency(request: Request, user=Depends(get_current_active_user), db: Session = Depends(get_db)):
        request.state.iam_permission = code
        check(db, user, code)
        return user
    return dependency


def audit(db, request, actor, module, action, target, *, before=None, after=None, outcome="success", details=None):
    payload = dict(details or {})
    if before is not None:
        payload["before"] = before
    if after is not None:
        payload["after"] = after
    row = im.ManagementAudit(
        actor=actor.username if hasattr(actor, "username") else actor,
        module=module, action=action, target=str(target), outcome=outcome,
        client_ip=request.client.host if request.client else "",
        request_id=getattr(request.state, "request_id", "") or str(uuid.uuid4()),
        details_json=json.dumps(payload, ensure_ascii=False, default=str),
    )
    db.add(row)
    request.state.iam_audited = True
    return row


def commit(db):
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        fail("conflict", "数据重复或仍有关联记录，请刷新后重试", "Duplicate data or linked records. Refresh and retry", 409)


def validate_password(value):
    if len(value) < 8 or len(value.encode("utf-8")) > 72:
        fail("password_invalid", "密码至少 8 位，UTF-8 长度不超过 72 字节", "Password must have at least 8 characters and at most 72 UTF-8 bytes")
    return value


def role_codes(db, name):
    role = db.get(im.Role, name)
    if role is None:
        fail("role_not_found", "角色不存在", "Role not found", 404)
    codes = set(PERMISSIONS) if name == "super_admin" else set(db.scalars(
        select(im.RolePermission.permission_code).where(im.RolePermission.role_name == name)))
    return role, codes


def manageable_role(db, actor, name):
    role, codes = role_codes(db, name)
    if name == "super_admin" and actor.role != "super_admin":
        fail("role_out_of_scope", "此角色超出可管理范围", "This role is outside your management scope", 403)
    if not codes <= permission_codes(db, actor):
        fail("role_out_of_scope", "此角色超出可管理范围", "This role is outside your management scope", 403)
    return role


def account_snapshot(db, user):
    return {
        "id": user.id, "username": user.username, "email": user.email,
        "role": user.role, "is_active": user.is_active,
        "group_ids": list(db.scalars(select(models.UserGroupMember.group_id).where(models.UserGroupMember.user_id == user.id))),
        "created_at": user.created_at, "last_login_at": user.last_login_at,
    }


def sync_groups(db, user, group_ids):
    ids = set(group_ids)
    found = set(db.scalars(select(models.UserGroup.id).where(models.UserGroup.id.in_(ids))))
    if ids != found:
        fail("group_not_found", "用户组不存在", "User group not found")
    db.query(models.UserGroupMember).filter_by(user_id=user.id).delete()
    db.add_all(models.UserGroupMember(user_id=user.id, group_id=gid) for gid in sorted(ids))
    db.flush()


def protect_account(db, actor, user, *, role=None, active=None, deleting=False):
    manageable_role(db, actor, user.role)
    if user.id == actor.id and (deleting or active is False or (role is not None and role != user.role)):
        fail("self_lockout", "不能删除、禁用自己或修改自己的角色", "You cannot delete, disable, or change the role of your own account")
    losing_admin = deleting or active is False or (role is not None and role not in {"admin", "super_admin"})
    if user.is_active and user.role in {"admin", "super_admin"} and losing_admin:
        other = db.query(models.User).filter(models.User.id != user.id, models.User.is_active.is_(True), models.User.role.in_(["admin", "super_admin"])).first()
        if other is None:
            fail("last_admin", "必须保留至少一个有效管理账号", "At least one active administrator must remain")


def create_account(db, request, actor, data):
    from .auth import get_password_hash
    from .iam_schemas import AccountCreate
    check(db, actor, "users:create")
    check(db, actor, "users:assign_role")
    data = validate_account_data(AccountCreate, data)
    manageable_role(db, actor, data["role"])
    user = models.User(username=data["username"], email=data.get("email") or None,
                       role=data["role"], is_active=data.get("is_active", True),
                       hashed_password=get_password_hash(validate_password(data["password"])))
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        fail("account_exists", "用户名或邮箱已存在", "Username or email already exists", 409)
    sync_groups(db, user, data.get("group_ids", []))
    audit(db, request, actor, "users", "create", user.id, after=account_snapshot(db, user))
    commit(db)
    return account_snapshot(db, user)


def update_account(db, request, actor, user, data):
    from .auth import get_password_hash
    from .iam_schemas import AccountUpdate
    if not data:
        fail("empty_update", "请提供需要修改的字段", "Provide fields to update")
    validated = validate_account_data(AccountUpdate, {key: value for key, value in data.items() if key != "password"})
    if "password" in data:
        validated["password"] = data["password"]
    data = validated
    protect_account(db, actor, user, role=data.get("role"), active=data.get("is_active"))
    before = account_snapshot(db, user)
    actions = []
    for field, action in (("role", "assign_role"), ("is_active", "set_status"), ("password", "reset_password"), ("email", "update"), ("group_ids", "update")):
        if field not in data or (field == "password" and not data[field]):
            continue
        check(db, actor, f"users:{action}")
        actions.append(action)
        if field == "role":
            manageable_role(db, actor, data[field])
            user.role = data[field]
        elif field == "password":
            user.hashed_password = get_password_hash(validate_password(data[field]))
            user.current_session_id = str(uuid.uuid4())
        elif field == "group_ids":
            sync_groups(db, user, data[field])
        else:
            setattr(user, field, data[field] or None if field == "email" else data[field])
            if field == "is_active" and not data[field]:
                user.current_session_id = str(uuid.uuid4())
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        fail("account_exists", "用户名或邮箱已存在", "Username or email already exists", 409)
    after = account_snapshot(db, user)
    for action in sorted(set(actions)):
        audit(db, request, actor, "users", action, user.id, before=before, after=after)
    commit(db)
    return after


def validate_account_data(schema, data):
    try:
        return schema.model_validate(data).model_dump(exclude_unset=True)
    except ValidationError as error:
        fields = sorted({str(item["loc"][0]) for item in error.errors(include_input=False) if item["loc"]})
        fail("invalid_account", "账号字段格式无效，请检查输入", "Invalid account fields. Check the supplied values", 422, fields=fields)


def menu_dict(row):
    return {column.name: getattr(row, column.name) for column in im.Menu.__table__.columns}


def visible_navigation(db, codes):
    from .feature_flags import feature_flags
    flags = feature_flags()
    rows = db.query(im.Menu).order_by(im.Menu.sort_order, im.Menu.name).all()
    def children(parent, ancestors):
        result = []
        for row in rows:
            if row.parent_name != parent or not row.is_active or row.name in ancestors:
                continue
            if PAGE_FEATURES.get(row.path) and not flags.get(PAGE_FEATURES[row.path], False):
                continue
            nested = children(row.name, ancestors | {row.name})
            allowed = PAGE_PERMISSIONS.get(row.path) in codes
            if row.path == "/system-audit":
                allowed = bool(codes & {"audit:login", "audit:operation", "audit:security"})
            if (row.path and allowed) or (not row.path and nested):
                result.append({**menu_dict(row), "children": nested, "feature": PAGE_FEATURES.get(row.path)})
        return result
    return children(None, set())


def access_snapshot(db, user):
    codes = permission_codes(db, user)
    navigation = visible_navigation(db, codes)
    def paths(items):
        return [p for item in items for p in ([item["path"]] if item["path"] else paths(item["children"]))]
    allowed = paths(navigation)
    role = db.get(im.Role, user.role)
    default = role.default_path if role and role.default_path in allowed else (allowed[0] if allowed else "/access-denied")
    return {"permissions": sorted(codes), "menus": navigation, "default_path": default, "page_permissions": PAGE_PERMISSIONS}
