import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import and_, case, func, literal, or_, select, union_all
from sqlalchemy.orm import Session

from .. import auth, iam, iam_models as im, iam_schemas as s, models
from ..iam_catalog import ICONS, MODULE_ACTIONS, PAGE_PERMISSIONS, PERMISSIONS, SENSITIVE_PERMISSIONS
from ..sqlite_db import get_db

router = APIRouter(prefix="/v1/iam", tags=["Identity management"])


def find(db, model, key):
    row = db.get(model, key)
    if row is None:
        iam.fail("not_found", "记录不存在", "Record not found", 404)
    return row


def paged(query, page, page_size, encode):
    return {"items": [encode(row) for row in query.offset((page - 1) * page_size).limit(page_size)],
            "total": query.order_by(None).count(), "page": page, "page_size": page_size}


@router.get("/access")
def access(db: Session = Depends(get_db), user=Depends(auth.get_current_active_user)):
    return iam.access_snapshot(db, user)


@router.get("/options")
def options(db: Session = Depends(get_db), user=Depends(auth.get_current_active_user)):
    codes = iam.permission_codes(db, user)
    if not codes & {f"{m}:{a}" for m in ("users", "roles", "menus") for a in ("view", "create", "update")}:
        iam.fail("permission_denied", "没有此操作权限", "Permission denied", 403)
    roles = []
    for row in db.query(im.Role).order_by(im.Role.name):
        _, target_codes = iam.role_codes(db, row.name)
        grantable = codes.copy()
        if user.role not in {"admin", "super_admin"}:
            grantable -= SENSITIVE_PERMISSIONS
        if row.name != "privacy_auditor":
            grantable -= {"privacy_audit:raw", "traces:raw"}
        if row.name in {"admin", "super_admin"}:
            grantable = set()
        roles.append({"name": row.name, "display_name": row.display_name, "description": row.description,
                      "display_key": row.display_key, "is_system": row.is_system, "grantable_permissions": sorted(grantable),
                      "assignable": target_codes <= codes and (row.name != "super_admin" or user.role == "super_admin")})
    groups = [{"id": g.id, "name": g.name} for g in db.query(models.UserGroup).order_by(models.UserGroup.name)] if codes & {"users:view", "users:create", "users:update"} else []
    def paths(items):
        return [p for item in items for p in ([item["path"]] if item["path"] else paths(item["children"]))]
    return {"roles": roles, "groups": groups, "pages": PAGE_PERMISSIONS,
            "home_pages": paths(iam.visible_navigation(db, PERMISSIONS)), "icons": sorted(ICONS), "modules": MODULE_ACTIONS}


@router.get("/users")
def users(q: str = Query("", max_length=128), role: str | None = None, active: bool | None = None,
          group_id: int | None = None, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
          sort: str = Query("created_at", pattern="^(created_at|last_login_at)$"),
          order: str = Query("desc", pattern="^(asc|desc)$"),
          db: Session = Depends(get_db), user=Depends(iam.require("users:view"))):
    query = db.query(models.User)
    if q:
        query = query.filter(or_(models.User.username.contains(q, autoescape=True), models.User.email.contains(q, autoescape=True)))
    if role:
        query = query.filter(models.User.role == role)
    if active is not None:
        query = query.filter(models.User.is_active == active)
    if group_id is not None:
        query = query.filter(models.User.id.in_(select(models.UserGroupMember.user_id).where(models.UserGroupMember.group_id == group_id)))
    column = getattr(models.User, sort)
    query = query.order_by(column.asc() if order == "asc" else column.desc(), models.User.id)
    return paged(query, page, page_size, lambda row: iam.account_snapshot(db, row))


@router.post("/users")
def create_user(body: s.AccountCreate, request: Request, db: Session = Depends(get_db), user=Depends(iam.require("users:create"))):
    return iam.create_account(db, request, user, body.model_dump())


@router.put("/users/{user_id}")
def update_user(user_id: int, body: s.AccountUpdate, request: Request, db: Session = Depends(get_db), user=Depends(auth.get_current_active_user)):
    return iam.update_account(db, request, user, find(db, models.User, user_id), body.model_dump(exclude_unset=True))


@router.post("/users/{user_id}/password")
def reset_password(user_id: int, body: s.PasswordReset, request: Request, db: Session = Depends(get_db), user=Depends(iam.require("users:reset_password"))):
    return iam.update_account(db, request, user, find(db, models.User, user_id), body.model_dump())


@router.delete("/users/{user_id}")
def delete_user(user_id: int, request: Request, db: Session = Depends(get_db), user=Depends(iam.require("users:delete"))):
    target = find(db, models.User, user_id)
    iam.protect_account(db, user, target, deleting=True)
    references = []
    # Inspect actual account foreign keys so new business associations also participate.
    for table in models.User.metadata.sorted_tables:
        if table.name == models.UserGroupMember.__tablename__:
            continue
        for column in table.columns:
            if any(fk.target_fullname == "users.id" for fk in column.foreign_keys):
                if db.scalar(select(func.count()).select_from(table).where(column == user_id)):
                    references.append(table.name)
    if references:
        iam.fail("account_in_use", "账号仍有关联记录，请先处理关联或禁用账号", "This account has linked records. Resolve them or disable the account", 409, resources=references)
    before = iam.account_snapshot(db, target)
    db.query(models.UserGroupMember).filter_by(user_id=user_id).delete()
    db.delete(target)
    iam.audit(db, request, user, "users", "delete", user_id, before=before)
    iam.commit(db)
    return {"deleted": True}


def role_dict(db, row):
    return {"name": row.name, "display_name": row.display_name, "description": row.description,
            "display_key": row.display_key,
            "default_path": row.default_path, "is_system": row.is_system, "created_at": row.created_at,
            "user_count": db.query(models.User).filter_by(role=row.name).count(),
            "permissions": sorted(iam.role_codes(db, row.name)[1])}


@router.get("/roles")
def roles(q: str = Query("", max_length=128), page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
          db: Session = Depends(get_db), user=Depends(iam.require("roles:view"))):
    query = db.query(im.Role)
    if q:
        query = query.filter(or_(im.Role.name.contains(q, autoescape=True), im.Role.display_name.contains(q, autoescape=True)))
    return paged(query.order_by(im.Role.is_system.desc(), im.Role.name), page, page_size, lambda row: role_dict(db, row))


def validate_home(db, path, codes):
    if not path:
        return
    def paths(items):
        return {p for item in items for p in ([item["path"]] if item["path"] else paths(item["children"]))}
    if path not in paths(iam.visible_navigation(db, codes)):
        iam.fail("invalid_home", "默认首页必须是角色可以访问的已启用页面", "The default page must be enabled and accessible to this role")


@router.post("/roles")
def create_role(body: s.RoleCreate, request: Request, db: Session = Depends(get_db), user=Depends(iam.require("roles:create"))):
    validate_home(db, body.default_path, set())
    row = im.Role(**body.model_dump())
    db.add(row)
    iam.audit(db, request, user, "roles", "create", body.name, after=body.model_dump())
    iam.commit(db)
    return role_dict(db, row)


@router.put("/roles/{name}")
def update_role(name: str, body: s.RoleUpdate, request: Request, db: Session = Depends(get_db), user=Depends(iam.require("roles:update"))):
    row = iam.manageable_role(db, user, name)
    validate_home(db, body.default_path, iam.role_codes(db, name)[1])
    before = role_dict(db, row)
    if row.display_name != body.display_name:
        row.display_key = None
    for field, value in body.model_dump().items():
        setattr(row, field, value)
    iam.audit(db, request, user, "roles", "update", name, before=before, after=role_dict(db, row))
    iam.commit(db)
    return role_dict(db, row)


@router.put("/roles/{name}/permissions")
def grant(name: str, body: s.Grant, request: Request, db: Session = Depends(get_db), user=Depends(iam.require("roles:grant"))):
    row = iam.manageable_role(db, user, name)
    codes = set(body.permissions)
    if len(codes) != len(body.permissions) or not codes <= PERMISSIONS:
        iam.fail("invalid_permissions", "权限重复或不存在", "Permissions are duplicated or unknown")
    if name in {"super_admin", "admin"}:
        iam.fail("protected_role", "最高管理角色的权限由系统维护", "Administrator permissions are maintained by the system")
    if not codes <= iam.permission_codes(db, user):
        iam.fail("grant_out_of_scope", "不能授予超出自身范围的权限", "You cannot grant permissions outside your scope", 403)
    if codes & SENSITIVE_PERMISSIONS and user.role not in {"admin", "super_admin"}:
        iam.fail("sensitive_grant", "敏感原文权限只能由管理员授予", "Only administrators can grant access to sensitive originals", 403)
    # Pipeline originals remain restricted to the existing privacy audit roles.
    if codes & {"privacy_audit:raw", "traces:raw"} and name != "privacy_auditor":
        iam.fail("sensitive_role", "原始隐私数据权限仅适用于隐私审计角色", "Original private data access is restricted to the privacy auditor role")
    if name == user.role and "roles:grant" not in codes:
        iam.fail("self_lockout", "不能移除自己的授权管理权限", "You cannot remove your own permission management access")
    validate_home(db, body.default_path, codes)
    before = role_dict(db, row)
    db.query(im.RolePermission).filter_by(role_name=name).delete()
    db.add_all(im.RolePermission(role_name=name, permission_code=code) for code in sorted(codes))
    row.default_path = body.default_path
    iam.audit(db, request, user, "roles", "grant", name, before=before,
              after={"permissions": sorted(codes), "default_path": body.default_path},
              details={"added": sorted(codes - set(before["permissions"])), "removed": sorted(set(before["permissions"]) - codes)})
    iam.commit(db)
    return role_dict(db, row)


@router.delete("/roles/{name}")
def delete_role(name: str, request: Request, db: Session = Depends(get_db), user=Depends(iam.require("roles:delete"))):
    row = iam.manageable_role(db, user, name)
    if row.is_system:
        iam.fail("protected_role", "系统角色不能删除", "System roles cannot be deleted")
    if db.query(models.User).filter_by(role=name).first():
        iam.fail("role_in_use", "请先调整使用此角色的账号", "Reassign accounts using this role first", 409)
    before = role_dict(db, row)
    db.query(im.RolePermission).filter_by(role_name=name).delete()
    db.delete(row)
    iam.audit(db, request, user, "roles", "delete", name, before=before)
    iam.commit(db)
    return {"deleted": True}


@router.get("/menus")
def menus(db: Session = Depends(get_db), user=Depends(iam.require("menus:view"))):
    return [iam.menu_dict(row) for row in db.query(im.Menu).order_by(im.Menu.sort_order, im.Menu.name)]


def validate_menu(db, name, data):
    if data["icon"] not in ICONS or (data["path"] and data["path"] not in PAGE_PERMISSIONS):
        iam.fail("invalid_menu", "请选择支持的图标和现有页面", "Select a supported icon and an existing page")
    parent = data["parent_name"]
    seen = {name}
    depth = 1
    while parent:
        if parent in seen:
            iam.fail("menu_cycle", "菜单不能循环引用", "Menu hierarchy cannot contain a cycle")
        seen.add(parent)
        row = find(db, im.Menu, parent)
        if row.path:
            iam.fail("page_parent", "页面不能作为父目录", "A page cannot be a parent directory")
        parent = row.parent_name
        depth += 1
    def subtree(node, visited):
        if node in visited:
            iam.fail("menu_cycle", "菜单不能循环引用", "Menu hierarchy cannot contain a cycle")
        return 1 + max((subtree(child.name, visited | {node}) for child in db.query(im.Menu).filter_by(parent_name=node)), default=0)
    height = subtree(name, set())
    if depth + height - 1 > 3:
        iam.fail("menu_depth", "菜单最多支持三级", "Menus support up to three levels")
    if data["path"] and height > 1:
        iam.fail("directory_has_children", "包含子菜单的目录不能改为页面", "A directory with children cannot become a page")
    old = db.get(im.Menu, name)
    if old and old.path and old.path != data["path"] and db.query(im.Role).filter_by(default_path=old.path).first():
        iam.fail("menu_home_in_use", "请先调整使用该页面作为首页的角色", "Update roles using this page as their home first", 409)


@router.post("/menus")
def create_menu(body: s.MenuCreate, request: Request, db: Session = Depends(get_db), user=Depends(iam.require("menus:create"))):
    validate_menu(db, body.name, body.model_dump())
    row = im.Menu(**body.model_dump())
    db.add(row)
    iam.audit(db, request, user, "menus", "create", body.name, after=body.model_dump())
    iam.commit(db)
    return iam.menu_dict(row)


@router.put("/menus/{name}")
def update_menu(name: str, body: s.MenuUpdate, request: Request, db: Session = Depends(get_db), user=Depends(iam.require("menus:update"))):
    row = find(db, im.Menu, name)
    if row.is_active != body.is_active:
        iam.check(db, user, "menus:set_status")
    if row.sort_order != body.sort_order or row.parent_name != body.parent_name:
        iam.check(db, user, "menus:sort")
    validate_menu(db, name, body.model_dump())
    before = iam.menu_dict(row)
    if row.title_zh != body.title_zh or row.title_en != body.title_en:
        row.title_key = None
    for field, value in body.model_dump().items():
        setattr(row, field, value)
    iam.audit(db, request, user, "menus", "update", name, before=before, after=iam.menu_dict(row))
    iam.commit(db)
    return iam.menu_dict(row)


@router.post("/menus/{name}/move")
def move_menu(name: str, body: s.Move, request: Request, db: Session = Depends(get_db), user=Depends(iam.require("menus:sort"))):
    row = find(db, im.Menu, name)
    siblings = db.query(im.Menu).filter_by(parent_name=row.parent_name).order_by(im.Menu.sort_order, im.Menu.name).all()
    index = next(i for i, item in enumerate(siblings) if item.name == name)
    other = index + (-1 if body.direction == "up" else 1)
    before = [item.name for item in siblings]
    if 0 <= other < len(siblings):
        siblings[index], siblings[other] = siblings[other], siblings[index]
        for i, item in enumerate(siblings):
            item.sort_order = i
    iam.audit(db, request, user, "menus", "sort", name, before=before, after=[item.name for item in siblings])
    iam.commit(db)
    return {"moved": 0 <= other < len(siblings)}


@router.post("/menus/{name}/status")
def menu_status(name: str, body: s.Status, request: Request, db: Session = Depends(get_db), user=Depends(iam.require("menus:set_status"))):
    row = find(db, im.Menu, name)
    before = iam.menu_dict(row)
    row.is_active = body.is_active
    iam.audit(db, request, user, "menus", "set_status", name, before=before, after=iam.menu_dict(row))
    iam.commit(db)
    return iam.menu_dict(row)


@router.delete("/menus/{name}")
def delete_menu(name: str, request: Request, db: Session = Depends(get_db), user=Depends(iam.require("menus:delete"))):
    row = find(db, im.Menu, name)
    if row.is_system:
        iam.fail("protected_menu", "内置入口请通过启停管理", "Use enabled status to manage built-in entries")
    if db.query(im.Menu).filter_by(parent_name=name).first():
        iam.fail("menu_has_children", "请先处理子菜单", "Handle child menus first", 409)
    if row.path and db.query(im.Role).filter_by(default_path=row.path).first():
        iam.fail("menu_home_in_use", "请先调整关联角色的默认首页", "Update the default page of linked roles first", 409)
    iam.audit(db, request, user, "menus", "delete", name, before=iam.menu_dict(row))
    db.delete(row)
    iam.commit(db)
    return {"deleted": True}


@router.get("/audit/{kind}")
def audit_events(kind: str, request: Request, q: str = Query("", max_length=128), actor: str = Query("", max_length=128),
                 module: str = Query("", max_length=64), action: str = Query("", max_length=64),
                 outcome: str = Query("", max_length=64), since: datetime | None = None, until: datetime | None = None,
                 page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                 db: Session = Depends(get_db), user=Depends(auth.get_current_active_user)):
    if kind not in {"login", "operation", "security"}:
        iam.fail("invalid_audit_kind", "日志类型无效", "Invalid audit type")
    request.state.iam_permission = f"audit:{kind}"
    iam.check(db, user, f"audit:{kind}")
    since = since.astimezone(timezone.utc).replace(tzinfo=None) if since and since.tzinfo else since
    until = until.astimezone(timezone.utc).replace(tzinfo=None) if until and until.tzinfo else until
    if since and until and since > until:
        iam.fail("invalid_date_range", "开始时间不能晚于结束时间", "Start time must not be after end time")
    if kind == "login":
        m = models.LoginLog
        query = select(m.id, m.created_at, m.username.label("actor"), literal("auth").label("module"),
                       literal("login").label("action"), m.username.label("target"),
                       case((m.status.in_(["Success", "success"]), "success"), else_="failed").label("outcome"),
                       m.ip_address.label("client_ip"), m.request_id,
                       m.status.label("details_json"), literal("login").label("source")).subquery()
    elif kind == "operation":
        m, old = im.ManagementAudit, models.OperationLog
        query = union_all(
            select(m.id, m.created_at, m.actor, m.module, m.action, m.target, m.outcome, m.client_ip, m.request_id, m.details_json, literal("management").label("source")),
            select(old.id, old.created_at, old.username, literal("legacy"), old.action, old.target, literal("success"), literal(""), literal(""), old.details, literal("legacy")),
        ).subquery()
    else:
        m = models.SecurityAuditEvent
        query = select(m.id, m.timestamp.label("created_at"), m.actor, m.resource_type.label("module"),
                       m.action, m.resource_id.label("target"),
                       case((m.outcome == "failure", "failed"), else_=m.outcome).label("outcome"),
                       literal("").label("client_ip"), literal("").label("request_id"),
                       m.event_id, m.event_type, m.details_json, literal("security").label("source")).subquery()
    stmt = select(query)
    if q:
        search_fields = ["actor", "target", "request_id", "action"]
        if kind == "security":
            search_fields.extend(["event_id", "event_type"])
        stmt = stmt.where(or_(*(query.c[field].contains(q, autoescape=True) for field in search_fields)))
    for key, value in (("actor", actor), ("module", module), ("outcome", outcome)):
        if value:
            stmt = stmt.where(query.c[key] == value)
    if action:
        aliases = {"update": ["put", "patch"], "view": ["get", "read"], "submit": ["post"]}.get(action, [])
        stmt = stmt.where(or_(query.c.action == action,
                             and_(query.c.source != "legacy", query.c.action.in_(aliases))))
    for value, lower in ((since, True), (until, False)):
        if value:
            stmt = stmt.where(query.c.created_at >= value if lower else query.c.created_at <= value)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.execute(stmt.order_by(query.c.created_at.desc(), query.c.id.desc(), query.c.source).offset((page - 1) * page_size).limit(page_size)).mappings()
    items = []
    for row in rows:
        item = dict(row)
        raw = item.pop("details_json")
        if kind == "login":
            item["reason"] = {"Success": "success", "Failed": "invalid_credentials", "Failed (Disabled)": "account_disabled"}.get(raw, raw)
        try:
            item["details"] = json.loads(raw or "{}")
        except (ValueError, TypeError):
            item["details"] = {"original": raw}
        item["key"] = f"{item['source']}:{item['id']}"
        items.append(item)
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.post("/audit-chain/verify")
def verify_chain(request: Request, db: Session = Depends(get_db), user=Depends(iam.require("audit:verify"))):
    from ..security_audit import verify_security_audit
    result = verify_security_audit(bind=db.get_bind())
    iam.audit(db, request, user, "audit", "verify", "security-chain", details=result)
    iam.commit(db)
    return result
