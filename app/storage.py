"""
Storage Layer — Abstraction d'accès aux données (SQLite async)
Point clé de toute la pipeline : centralise tout accès aux données
"""

import aiosqlite
import uuid
from datetime import datetime
from typing import Optional, List, Set
from contextlib import asynccontextmanager

from .models import (
    User, UserCreate,
    Group, GroupCreate,
    Page, PageCreate,
    PagePermission, PagePermissionCreate,
    Alarm, AlarmCreate,
    AlarmEvent, AlarmEventCreate,
    SubjectType
)


# ─────────────────────────────────────────────────────────────
# DATABASE PATH
# ─────────────────────────────────────────────────────────────

DB_PATH = "data/alarms.db"


# ─────────────────────────────────────────────────────────────
# DATABASE CONNECTION
# ─────────────────────────────────────────────────────────────

@asynccontextmanager
async def get_db():
    """Connexion async à la DB"""
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    try:
        yield db
    finally:
        await db.close()


# ─────────────────────────────────────────────────────────────
# INIT DATABASE — SCHÉMA COMPLET (ÉTAPE 4)
# ─────────────────────────────────────────────────────────────

async def init_db():
    """Crée toutes les tables si elles n'existent pas"""
    async with get_db() as db:
        # Users
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at DATETIME NOT NULL
            )
        """)
        
        # Groups
        await db.execute("""
            CREATE TABLE IF NOT EXISTS groups (
                id TEXT PRIMARY KEY,
                name TEXT UNIQUE NOT NULL
            )
        """)
        
        # User ↔ Groups (many-to-many)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_groups (
                user_id TEXT NOT NULL,
                group_id TEXT NOT NULL,
                PRIMARY KEY (user_id, group_id),
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (group_id) REFERENCES groups(id) ON DELETE CASCADE
            )
        """)
        
        # Pages (unité centrale de permissions)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS pages (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                owner_id TEXT NOT NULL,
                created_at DATETIME NOT NULL,
                FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)
        
        # Page Permissions (TABLE CLÉ)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS page_permissions (
                page_id TEXT NOT NULL,
                subject_type TEXT NOT NULL CHECK(subject_type IN ('user', 'group')),
                subject_id TEXT NOT NULL,
                can_view INTEGER NOT NULL DEFAULT 1,
                can_edit INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (page_id, subject_type, subject_id),
                FOREIGN KEY (page_id) REFERENCES pages(id) ON DELETE CASCADE
            )
        """)
        
        # Alarms (héritent des permissions de la page)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS alarms (
                id TEXT PRIMARY KEY,
                page_id TEXT NOT NULL,
                ticker TEXT NOT NULL,
                option TEXT NOT NULL,
                condition TEXT NOT NULL,
                created_by TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                created_at DATETIME NOT NULL,
                last_triggered DATETIME,
                FOREIGN KEY (page_id) REFERENCES pages(id) ON DELETE CASCADE,
                FOREIGN KEY (created_by) REFERENCES users(id)
            )
        """)
        
        # Alarm Events (historique / audit)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS alarm_events (
                id TEXT PRIMARY KEY,
                alarm_id TEXT NOT NULL,
                triggered_by TEXT NOT NULL,
                price REAL,
                triggered_at DATETIME NOT NULL,
                FOREIGN KEY (alarm_id) REFERENCES alarms(id) ON DELETE CASCADE,
                FOREIGN KEY (triggered_by) REFERENCES users(id)
            )
        """)
        
        # Index pour performances
        await db.execute("CREATE INDEX IF NOT EXISTS idx_alarms_page ON alarms(page_id)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_permissions_subject ON page_permissions(subject_type, subject_id)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_user_groups_user ON user_groups(user_id)")
        
        await db.commit()


# ─────────────────────────────────────────────────────────────
# USERS
# ─────────────────────────────────────────────────────────────

async def create_user(user: UserCreate, password_hash: str) -> User:
    """Crée un nouvel utilisateur"""
    user_id = str(uuid.uuid4())
    created_at = datetime.utcnow()
    
    async with get_db() as db:
        await db.execute(
            "INSERT INTO users (id, username, password_hash, created_at) VALUES (?, ?, ?, ?)",
            (user_id, user.username, password_hash, created_at)
        )
        await db.commit()
    
    return User(id=user_id, username=user.username, created_at=created_at)


async def get_user_by_username(username: str) -> Optional[tuple]:
    """Récupère un user par son username (avec hash pour auth)"""
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT id, username, password_hash, created_at FROM users WHERE username = ?",
            (username,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_user_by_id(user_id: str) -> Optional[User]:
    """Récupère un user par son ID"""
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT id, username, created_at FROM users WHERE id = ?",
            (user_id,)
        )
        row = await cursor.fetchone()
        if row:
            return User(id=row["id"], username=row["username"], created_at=row["created_at"])
        return None


# ─────────────────────────────────────────────────────────────
# GROUPS
# ─────────────────────────────────────────────────────────────

async def create_group(group: GroupCreate) -> Group:
    """Crée un nouveau groupe"""
    group_id = str(uuid.uuid4())
    
    async with get_db() as db:
        await db.execute(
            "INSERT INTO groups (id, name) VALUES (?, ?)",
            (group_id, group.name)
        )
        await db.commit()
    
    return Group(id=group_id, name=group.name)


async def add_user_to_group(user_id: str, group_id: str) -> bool:
    """Ajoute un utilisateur à un groupe"""
    async with get_db() as db:
        try:
            await db.execute(
                "INSERT INTO user_groups (user_id, group_id) VALUES (?, ?)",
                (user_id, group_id)
            )
            await db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False


async def get_user_groups(user_id: str) -> List[str]:
    """Récupère les IDs des groupes d'un utilisateur"""
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT group_id FROM user_groups WHERE user_id = ?",
            (user_id,)
        )
        rows = await cursor.fetchall()
        return [row["group_id"] for row in rows]


# ─────────────────────────────────────────────────────────────
# PAGES
# ─────────────────────────────────────────────────────────────

async def create_page(page: PageCreate, owner_id: str) -> Page:
    """Crée une nouvelle page"""
    page_id = str(uuid.uuid4())
    created_at = datetime.utcnow()
    
    async with get_db() as db:
        await db.execute(
            "INSERT INTO pages (id, name, owner_id, created_at) VALUES (?, ?, ?, ?)",
            (page_id, page.name, owner_id, created_at)
        )
        await db.commit()
    
    return Page(id=page_id, name=page.name, owner_id=owner_id, created_at=created_at)


async def get_page_by_id(page_id: str) -> Optional[Page]:
    """Récupère une page par son ID"""
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT id, name, owner_id, created_at FROM pages WHERE id = ?",
            (page_id,)
        )
        row = await cursor.fetchone()
        if row:
            return Page(
                id=row["id"],
                name=row["name"],
                owner_id=row["owner_id"],
                created_at=row["created_at"]
            )
        return None


async def get_accessible_pages(user_id: str) -> List[Page]:
    """
    Récupère toutes les pages accessibles par un utilisateur
    (owner OU permission directe OU via groupe)
    """
    group_ids = await get_user_groups(user_id)
    
    async with get_db() as db:
        # Requête clé : pages visibles par user
        query = """
            SELECT DISTINCT p.id, p.name, p.owner_id, p.created_at
            FROM pages p
            LEFT JOIN page_permissions pp ON p.id = pp.page_id
            WHERE 
                p.owner_id = ?
                OR (pp.subject_type = 'user' AND pp.subject_id = ? AND pp.can_view = 1)
        """
        params = [user_id, user_id]
        
        # Ajouter condition groupes si l'user a des groupes
        if group_ids:
            placeholders = ",".join("?" * len(group_ids))
            query += f" OR (pp.subject_type = 'group' AND pp.subject_id IN ({placeholders}) AND pp.can_view = 1)"
            params.extend(group_ids)
        
        cursor = await db.execute(query, params)
        rows = await cursor.fetchall()
        
        return [
            Page(
                id=row["id"],
                name=row["name"],
                owner_id=row["owner_id"],
                created_at=row["created_at"]
            )
            for row in rows
        ]


async def can_user_view_page(user_id: str, page_id: str) -> bool:
    """Vérifie si un utilisateur peut voir une page"""
    page = await get_page_by_id(page_id)
    if not page:
        return False
    
    # Owner a toujours accès
    if page.owner_id == user_id:
        return True
    
    group_ids = await get_user_groups(user_id)
    
    async with get_db() as db:
        query = """
            SELECT 1 FROM page_permissions
            WHERE page_id = ? AND can_view = 1 AND (
                (subject_type = 'user' AND subject_id = ?)
        """
        params = [page_id, user_id]
        
        if group_ids:
            placeholders = ",".join("?" * len(group_ids))
            query += f" OR (subject_type = 'group' AND subject_id IN ({placeholders}))"
            params.extend(group_ids)
        
        query += ")"
        
        cursor = await db.execute(query, params)
        row = await cursor.fetchone()
        return row is not None


async def can_user_edit_page(user_id: str, page_id: str) -> bool:
    """Vérifie si un utilisateur peut éditer une page"""
    page = await get_page_by_id(page_id)
    if not page:
        return False
    
    # Owner a toujours accès en édition
    if page.owner_id == user_id:
        return True
    
    group_ids = await get_user_groups(user_id)
    
    async with get_db() as db:
        query = """
            SELECT 1 FROM page_permissions
            WHERE page_id = ? AND can_edit = 1 AND (
                (subject_type = 'user' AND subject_id = ?)
        """
        params = [page_id, user_id]
        
        if group_ids:
            placeholders = ",".join("?" * len(group_ids))
            query += f" OR (subject_type = 'group' AND subject_id IN ({placeholders}))"
            params.extend(group_ids)
        
        query += ")"
        
        cursor = await db.execute(query, params)
        row = await cursor.fetchone()
        return row is not None


# ─────────────────────────────────────────────────────────────
# PAGE PERMISSIONS
# ─────────────────────────────────────────────────────────────

async def set_page_permission(permission: PagePermissionCreate) -> PagePermission:
    """Définit une permission sur une page (insert or replace)"""
    async with get_db() as db:
        await db.execute(
            """
            INSERT OR REPLACE INTO page_permissions 
            (page_id, subject_type, subject_id, can_view, can_edit)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                permission.page_id,
                permission.subject_type.value,
                permission.subject_id,
                1 if permission.can_view else 0,
                1 if permission.can_edit else 0
            )
        )
        await db.commit()
    
    return PagePermission(
        page_id=permission.page_id,
        subject_type=permission.subject_type,
        subject_id=permission.subject_id,
        can_view=permission.can_view,
        can_edit=permission.can_edit
    )


async def get_users_with_page_access(page_id: str) -> Set[str]:
    """
    Récupère tous les user_ids qui ont accès à une page
    (pour le broadcast WS ciblé)
    """
    async with get_db() as db:
        # Owner
        cursor = await db.execute(
            "SELECT owner_id FROM pages WHERE id = ?",
            (page_id,)
        )
        row = await cursor.fetchone()
        if not row:
            return set()
        
        user_ids = {row["owner_id"]}
        
        # Permissions directes user
        cursor = await db.execute(
            """
            SELECT subject_id FROM page_permissions
            WHERE page_id = ? AND subject_type = 'user' AND can_view = 1
            """,
            (page_id,)
        )
        rows = await cursor.fetchall()
        user_ids.update(row["subject_id"] for row in rows)
        
        # Permissions via groupes
        cursor = await db.execute(
            """
            SELECT ug.user_id FROM user_groups ug
            INNER JOIN page_permissions pp ON pp.subject_id = ug.group_id
            WHERE pp.page_id = ? AND pp.subject_type = 'group' AND pp.can_view = 1
            """,
            (page_id,)
        )
        rows = await cursor.fetchall()
        user_ids.update(row["user_id"] for row in rows)
        
        return user_ids


# ─────────────────────────────────────────────────────────────
# ALARMS
# ─────────────────────────────────────────────────────────────

async def create_alarm(alarm: AlarmCreate, created_by: str) -> Alarm:
    """Crée une nouvelle alarme"""
    alarm_id = str(uuid.uuid4())
    created_at = datetime.utcnow()
    
    async with get_db() as db:
        await db.execute(
            """
            INSERT INTO alarms 
            (id, page_id, ticker, option, condition, created_by, active, created_at)
            VALUES (?, ?, ?, ?, ?, ?, 1, ?)
            """,
            (
                alarm_id,
                alarm.page_id,
                alarm.ticker,
                alarm.option,
                alarm.condition.value,
                created_by,
                created_at
            )
        )
        await db.commit()
    
    return Alarm(
        id=alarm_id,
        page_id=alarm.page_id,
        ticker=alarm.ticker,
        option=alarm.option,
        condition=alarm.condition,
        created_by=created_by,
        active=True,
        created_at=created_at,
        last_triggered=None
    )


async def get_alarm_by_id(alarm_id: str) -> Optional[Alarm]:
    """Récupère une alarme par son ID"""
    async with get_db() as db:
        cursor = await db.execute(
            """
            SELECT id, page_id, ticker, option, condition, created_by, 
                   active, created_at, last_triggered
            FROM alarms WHERE id = ?
            """,
            (alarm_id,)
        )
        row = await cursor.fetchone()
        if row:
            return Alarm(
                id=row["id"],
                page_id=row["page_id"],
                ticker=row["ticker"],
                option=row["option"],
                condition=row["condition"],
                created_by=row["created_by"],
                active=bool(row["active"]),
                created_at=row["created_at"],
                last_triggered=row["last_triggered"]
            )
        return None


async def get_alarms_for_pages(page_ids: List[str]) -> List[Alarm]:
    """Récupère toutes les alarmes des pages spécifiées"""
    if not page_ids:
        return []
    
    async with get_db() as db:
        placeholders = ",".join("?" * len(page_ids))
        cursor = await db.execute(
            f"""
            SELECT id, page_id, ticker, option, condition, created_by,
                   active, created_at, last_triggered
            FROM alarms
            WHERE page_id IN ({placeholders})
            """,
            page_ids
        )
        rows = await cursor.fetchall()
        
        return [
            Alarm(
                id=row["id"],
                page_id=row["page_id"],
                ticker=row["ticker"],
                option=row["option"],
                condition=row["condition"],
                created_by=row["created_by"],
                active=bool(row["active"]),
                created_at=row["created_at"],
                last_triggered=row["last_triggered"]
            )
            for row in rows
        ]


async def update_alarm(alarm_id: str, **kwargs) -> Optional[Alarm]:
    """Met à jour une alarme"""
    allowed_fields = {"ticker", "option", "condition", "active"}
    updates = {k: v for k, v in kwargs.items() if k in allowed_fields}
    
    if not updates:
        return await get_alarm_by_id(alarm_id)
    
    set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
    values = list(updates.values())
    values.append(alarm_id)
    
    async with get_db() as db:
        await db.execute(
            f"UPDATE alarms SET {set_clause} WHERE id = ?",
            values
        )
        await db.commit()
    
    return await get_alarm_by_id(alarm_id)


async def delete_alarm(alarm_id: str) -> bool:
    """Supprime une alarme"""
    async with get_db() as db:
        cursor = await db.execute(
            "DELETE FROM alarms WHERE id = ?",
            (alarm_id,)
        )
        await db.commit()
        return cursor.rowcount > 0


async def trigger_alarm(alarm_id: str, triggered_by: str, price: Optional[float] = None) -> Optional[AlarmEvent]:
    """Déclenche une alarme et enregistre l'événement"""
    alarm = await get_alarm_by_id(alarm_id)
    if not alarm:
        return None
    
    event_id = str(uuid.uuid4())
    triggered_at = datetime.utcnow()
    
    async with get_db() as db:
        # Enregistrer l'événement
        await db.execute(
            """
            INSERT INTO alarm_events (id, alarm_id, triggered_by, price, triggered_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (event_id, alarm_id, triggered_by, price, triggered_at)
        )
        
        # Mettre à jour last_triggered
        await db.execute(
            "UPDATE alarms SET last_triggered = ? WHERE id = ?",
            (triggered_at, alarm_id)
        )
        
        await db.commit()
    
    return AlarmEvent(
        id=event_id,
        alarm_id=alarm_id,
        triggered_by=triggered_by,
        price=price,
        triggered_at=triggered_at
    )


# ─────────────────────────────────────────────────────────────
# ALARM EVENTS (historique)
# ─────────────────────────────────────────────────────────────

async def get_alarm_events(alarm_id: str, limit: int = 100) -> List[AlarmEvent]:
    """Récupère l'historique d'une alarme"""
    async with get_db() as db:
        cursor = await db.execute(
            """
            SELECT id, alarm_id, triggered_by, price, triggered_at
            FROM alarm_events
            WHERE alarm_id = ?
            ORDER BY triggered_at DESC
            LIMIT ?
            """,
            (alarm_id, limit)
        )
        rows = await cursor.fetchall()
        
        return [
            AlarmEvent(
                id=row["id"],
                alarm_id=row["alarm_id"],
                triggered_by=row["triggered_by"],
                price=row["price"],
                triggered_at=row["triggered_at"]
            )
            for row in rows
        ]
