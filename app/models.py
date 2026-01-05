"""
Modèles de données — Langage commun du serveur d'alarmes
Aucun accès DB ici — uniquement des structures de données
"""

from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, Literal
from enum import Enum


# ─────────────────────────────────────────────────────────────
# ENUMS
# ─────────────────────────────────────────────────────────────

class SubjectType(str, Enum):
    USER = "user"
    GROUP = "group"


class AlarmCondition(str, Enum):
    ABOVE = "above"
    BELOW = "below"
    CROSS = "cross"


# ─────────────────────────────────────────────────────────────
# USER & AUTH
# ─────────────────────────────────────────────────────────────

class UserBase(BaseModel):
    username: str


class UserCreate(UserBase):
    password: str


class User(UserBase):
    id: str
    created_at: datetime

    class Config:
        from_attributes = True


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    user_id: str
    username: str


# ─────────────────────────────────────────────────────────────
# GROUPS
# ─────────────────────────────────────────────────────────────

class GroupBase(BaseModel):
    name: str


class GroupCreate(GroupBase):
    pass


class Group(GroupBase):
    id: str

    class Config:
        from_attributes = True


# ─────────────────────────────────────────────────────────────
# PAGES
# ─────────────────────────────────────────────────────────────

class PageBase(BaseModel):
    name: str


class PageCreate(PageBase):
    pass


class Page(PageBase):
    id: str
    owner_id: str
    created_at: datetime

    class Config:
        from_attributes = True


# ─────────────────────────────────────────────────────────────
# PAGE PERMISSIONS
# ─────────────────────────────────────────────────────────────

class PagePermissionBase(BaseModel):
    subject_type: SubjectType
    subject_id: str
    can_view: bool = True
    can_edit: bool = False


class PagePermissionRequest(BaseModel):
    """Permission request pour l'API (sans page_id qui est dans l'URL)"""
    subject_type: SubjectType
    subject_id: str
    can_view: bool = True
    can_edit: bool = False


class PagePermissionCreate(PagePermissionBase):
    page_id: str


class PagePermission(PagePermissionBase):
    page_id: str

    class Config:
        from_attributes = True


# ─────────────────────────────────────────────────────────────
# ALARMS
# ─────────────────────────────────────────────────────────────

class AlarmBase(BaseModel):
    ticker: str
    option: str
    condition: AlarmCondition
    strategy_id: Optional[str] = None
    strategy_name: Optional[str] = None


class AlarmCreate(AlarmBase):
    page_id: str


class Alarm(AlarmBase):
    id: str
    page_id: str
    created_by: str
    active: bool = True
    created_at: datetime
    last_triggered: Optional[datetime] = None

    class Config:
        from_attributes = True


# ─────────────────────────────────────────────────────────────
# ALARM EVENTS (historique / audit)
# ─────────────────────────────────────────────────────────────

class AlarmEventBase(BaseModel):
    price: Optional[float] = None


class AlarmEventCreate(AlarmEventBase):
    alarm_id: str
    triggered_by: str


class AlarmEvent(AlarmEventBase):
    id: str
    alarm_id: str
    triggered_by: str
    triggered_at: datetime

    class Config:
        from_attributes = True


# ─────────────────────────────────────────────────────────────
# WEBSOCKET MESSAGES
# ─────────────────────────────────────────────────────────────

class WSMessage(BaseModel):
    """Message WebSocket générique"""
    type: str
    payload: dict = Field(default_factory=dict)


class WSAlarmUpdate(BaseModel):
    """Notification de mise à jour d'alarme"""
    alarm_id: str
    page_id: str
    action: Literal["created", "updated", "deleted", "triggered"]
    data: Optional[dict] = None
