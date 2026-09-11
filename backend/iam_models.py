"""Management identities, navigation, and transactional audit records."""
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text

from .sqlite_db import Base


class Role(Base):
    __tablename__ = "iam_roles"
    name = Column(String(64), primary_key=True)
    display_name = Column(String(128), nullable=False)
    display_key = Column(String(128), nullable=True)
    description = Column(Text, nullable=False, default="")
    default_path = Column(String(256), nullable=False, default="/dashboard")
    is_system = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class Permission(Base):
    __tablename__ = "iam_permissions"
    code = Column(String(128), primary_key=True)
    module = Column(String(64), nullable=False)
    action = Column(String(64), nullable=False)


class RolePermission(Base):
    __tablename__ = "iam_role_permissions"
    role_name = Column(String(64), ForeignKey("iam_roles.name"), primary_key=True)
    permission_code = Column(String(128), ForeignKey("iam_permissions.code"), primary_key=True)


class Menu(Base):
    __tablename__ = "iam_menus"
    name = Column(String(64), primary_key=True)
    parent_name = Column(String(64), ForeignKey("iam_menus.name"), nullable=True)
    title_zh = Column(String(128), nullable=False)
    title_en = Column(String(128), nullable=False)
    title_key = Column(String(128), nullable=True)
    icon = Column(String(32), nullable=False, default="setting")
    path = Column(String(256), nullable=True)
    sort_order = Column(Integer, nullable=False, default=0)
    is_active = Column(Boolean, nullable=False, default=True)
    is_system = Column(Boolean, nullable=False, default=False)


class ManagementAudit(Base):
    __tablename__ = "management_audit_events"
    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    actor = Column(String(128), nullable=False, index=True)
    module = Column(String(64), nullable=False, index=True)
    action = Column(String(64), nullable=False, index=True)
    target = Column(String(256), nullable=False, index=True)
    outcome = Column(String(32), nullable=False, default="success", index=True)
    client_ip = Column(String(128), nullable=False, default="")
    request_id = Column(String(64), nullable=False, default="", index=True)
    details_json = Column(Text, nullable=False, default="{}")
