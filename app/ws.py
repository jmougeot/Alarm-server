"""
WebSocket Layer — Temps réel avec broadcast ciblé par permissions
Le serveur filtre TOUT — pas de filtrage client
"""

import json
from typing import Dict, Set, Optional
from fastapi import WebSocket, WebSocketDisconnect

from .models import User, WSMessage, WSAlarmUpdate
from . import storage


# ─────────────────────────────────────────────────────────────
# CONNECTION MANAGER
# ─────────────────────────────────────────────────────────────

class ConnectionManager:
    """
    Gère les connexions WebSocket avec mapping user_id → connexions
    Permet le broadcast ciblé basé sur les permissions
    """
    
    def __init__(self):
        # user_id → set de WebSocket connections
        self._connections: Dict[str, Set[WebSocket]] = {}
        # WebSocket → user_id (reverse lookup)
        self._user_by_ws: Dict[WebSocket, str] = {}
    
    async def connect(self, websocket: WebSocket, user: User):
        """
        Connecte un utilisateur authentifié
        Un user peut avoir plusieurs connexions (multi-device)
        """
        await websocket.accept()
        
        user_id = user.id
        
        if user_id not in self._connections:
            self._connections[user_id] = set()
        
        self._connections[user_id].add(websocket)
        self._user_by_ws[websocket] = user_id
        
        # Envoyer les données initiales
        await self._send_initial_data(websocket, user)
    
    def disconnect(self, websocket: WebSocket):
        """Déconnecte un WebSocket"""
        user_id = self._user_by_ws.get(websocket)
        
        if user_id:
            self._connections[user_id].discard(websocket)
            
            # Nettoyer si plus de connexions
            if not self._connections[user_id]:
                del self._connections[user_id]
            
            del self._user_by_ws[websocket]
    
    def get_user_id(self, websocket: WebSocket) -> Optional[str]:
        """Récupère le user_id d'une connexion"""
        return self._user_by_ws.get(websocket)
    
    async def _send_initial_data(self, websocket: WebSocket, user: User):
        """
        Envoie les données initiales à la connexion :
        - Pages accessibles
        - Alarmes de ces pages
        """
        # Récupérer les pages accessibles
        pages = await storage.get_accessible_pages(user.id)
        page_ids = [p.id for p in pages]
        
        # Récupérer les alarmes de ces pages
        alarms = await storage.get_alarms_for_pages(page_ids)
        
        # Envoyer le state initial
        initial_state = WSMessage(
            type="initial_state",
            payload={
                "user": {
                    "id": user.id,
                    "username": user.username
                },
                "pages": [
                    {
                        "id": p.id,
                        "name": p.name,
                        "owner_id": p.owner_id,
                        "is_owner": p.owner_id == user.id
                    }
                    for p in pages
                ],
                "alarms": [
                    {
                        "id": a.id,
                        "page_id": a.page_id,
                        "ticker": a.ticker,
                        "option": a.option,
                        "condition": a.condition.value if hasattr(a.condition, 'value') else a.condition,
                        "active": a.active,
                        "last_triggered": a.last_triggered.isoformat() if a.last_triggered else None
                    }
                    for a in alarms
                ]
            }
        )
        
        await websocket.send_json(initial_state.model_dump())
    
    async def send_to_user(self, user_id: str, message: WSMessage):
        """Envoie un message à toutes les connexions d'un user"""
        connections = self._connections.get(user_id, set())
        
        for ws in connections.copy():
            try:
                await ws.send_json(message.model_dump())
            except Exception:
                # Connexion morte, nettoyer
                self.disconnect(ws)
    
    async def broadcast_to_page_users(self, page_id: str, message: WSMessage):
        """
        Broadcast ciblé : envoie uniquement aux users ayant accès à la page
        C'est LE mécanisme de sécurité temps réel
        """
        # Récupérer tous les users avec accès
        user_ids = await storage.get_users_with_page_access(page_id)
        
        # Envoyer à chacun
        for user_id in user_ids:
            await self.send_to_user(user_id, message)
    
    async def broadcast_alarm_update(self, alarm_update: WSAlarmUpdate):
        """Broadcast une mise à jour d'alarme aux users concernés"""
        message = WSMessage(
            type="alarm_update",
            payload=alarm_update.model_dump()
        )
        
        await self.broadcast_to_page_users(alarm_update.page_id, message)


# Singleton global
manager = ConnectionManager()


# ─────────────────────────────────────────────────────────────
# MESSAGE HANDLERS
# ─────────────────────────────────────────────────────────────

async def handle_message(websocket: WebSocket, user: User, data: dict):
    """
    Traite les messages entrants WebSocket
    Vérifie les permissions avant chaque action
    """
    msg_type = data.get("type")
    payload = data.get("payload", {})
    
    handlers = {
        "create_alarm": handle_create_alarm,
        "update_alarm": handle_update_alarm,
        "delete_alarm": handle_delete_alarm,
        "trigger_alarm": handle_trigger_alarm,
        "create_page": handle_create_page,
        "share_page": handle_share_page,
    }
    
    handler = handlers.get(msg_type)
    
    if handler:
        try:
            await handler(websocket, user, payload)
        except Exception as e:
            await send_error(websocket, str(e))
    else:
        await send_error(websocket, f"Unknown message type: {msg_type}")


async def send_error(websocket: WebSocket, error: str):
    """Envoie une erreur au client"""
    message = WSMessage(type="error", payload={"message": error})
    await websocket.send_json(message.model_dump())


async def send_success(websocket: WebSocket, action: str, data: dict = None):
    """Envoie une confirmation de succès"""
    message = WSMessage(
        type="success",
        payload={"action": action, "data": data or {}}
    )
    await websocket.send_json(message.model_dump())


# ─────────────────────────────────────────────────────────────
# HANDLERS SPÉCIFIQUES
# ─────────────────────────────────────────────────────────────

async def handle_create_alarm(websocket: WebSocket, user: User, payload: dict):
    """Crée une alarme (vérifie permission edit sur la page)"""
    from .models import AlarmCreate, AlarmCondition
    
    page_id = payload.get("page_id")
    
    # Vérifier permission
    if not await storage.can_user_edit_page(user.id, page_id):
        await send_error(websocket, "Permission denied: cannot edit this page")
        return
    
    # Créer l'alarme
    alarm_data = AlarmCreate(
        page_id=page_id,
        ticker=payload.get("ticker"),
        option=payload.get("option"),
        condition=AlarmCondition(payload.get("condition"))
    )
    
    alarm = await storage.create_alarm(alarm_data, user.id)
    
    # Notifier tous les users concernés
    update = WSAlarmUpdate(
        alarm_id=alarm.id,
        page_id=alarm.page_id,
        action="created",
        data={
            "id": alarm.id,
            "ticker": alarm.ticker,
            "option": alarm.option,
            "condition": alarm.condition.value,
            "active": alarm.active
        }
    )
    
    await manager.broadcast_alarm_update(update)


async def handle_update_alarm(websocket: WebSocket, user: User, payload: dict):
    """Met à jour une alarme"""
    alarm_id = payload.get("alarm_id")
    
    # Récupérer l'alarme
    alarm = await storage.get_alarm_by_id(alarm_id)
    if not alarm:
        await send_error(websocket, "Alarm not found")
        return
    
    # Vérifier permission
    if not await storage.can_user_edit_page(user.id, alarm.page_id):
        await send_error(websocket, "Permission denied: cannot edit this alarm")
        return
    
    # Mettre à jour
    updates = {k: v for k, v in payload.items() if k in ["ticker", "option", "condition", "active"]}
    updated_alarm = await storage.update_alarm(alarm_id, **updates)
    
    # Notifier
    update = WSAlarmUpdate(
        alarm_id=alarm_id,
        page_id=alarm.page_id,
        action="updated",
        data=updates
    )
    
    await manager.broadcast_alarm_update(update)


async def handle_delete_alarm(websocket: WebSocket, user: User, payload: dict):
    """Supprime une alarme"""
    alarm_id = payload.get("alarm_id")
    
    # Récupérer l'alarme
    alarm = await storage.get_alarm_by_id(alarm_id)
    if not alarm:
        await send_error(websocket, "Alarm not found")
        return
    
    # Vérifier permission
    if not await storage.can_user_edit_page(user.id, alarm.page_id):
        await send_error(websocket, "Permission denied: cannot delete this alarm")
        return
    
    page_id = alarm.page_id
    
    # Supprimer
    await storage.delete_alarm(alarm_id)
    
    # Notifier
    update = WSAlarmUpdate(
        alarm_id=alarm_id,
        page_id=page_id,
        action="deleted",
        data={}
    )
    
    await manager.broadcast_alarm_update(update)


async def handle_trigger_alarm(websocket: WebSocket, user: User, payload: dict):
    """Déclenche une alarme (notification temps réel)"""
    alarm_id = payload.get("alarm_id")
    price = payload.get("price")
    
    # Récupérer l'alarme
    alarm = await storage.get_alarm_by_id(alarm_id)
    if not alarm:
        await send_error(websocket, "Alarm not found")
        return
    
    # Vérifier permission (view suffit pour trigger)
    if not await storage.can_user_view_page(user.id, alarm.page_id):
        await send_error(websocket, "Permission denied: cannot access this alarm")
        return
    
    # Enregistrer le déclenchement
    event = await storage.trigger_alarm(alarm_id, user.id, price)
    
    # Notifier
    update = WSAlarmUpdate(
        alarm_id=alarm_id,
        page_id=alarm.page_id,
        action="triggered",
        data={
            "triggered_by": user.username,
            "price": price,
            "triggered_at": event.triggered_at.isoformat() if event else None
        }
    )
    
    await manager.broadcast_alarm_update(update)


async def handle_create_page(websocket: WebSocket, user: User, payload: dict):
    """Crée une nouvelle page"""
    from .models import PageCreate
    
    page_data = PageCreate(name=payload.get("name"))
    page = await storage.create_page(page_data, user.id)
    
    # Envoyer confirmation
    await send_success(websocket, "page_created", {
        "id": page.id,
        "name": page.name,
        "owner_id": page.owner_id
    })


async def handle_share_page(websocket: WebSocket, user: User, payload: dict):
    """Partage une page avec un user ou groupe"""
    from .models import PagePermissionCreate, SubjectType
    
    page_id = payload.get("page_id")
    
    # Vérifier que l'user est owner
    page = await storage.get_page_by_id(page_id)
    if not page or page.owner_id != user.id:
        await send_error(websocket, "Permission denied: only owner can share")
        return
    
    # Créer la permission
    permission_data = PagePermissionCreate(
        page_id=page_id,
        subject_type=SubjectType(payload.get("subject_type")),
        subject_id=payload.get("subject_id"),
        can_view=payload.get("can_view", True),
        can_edit=payload.get("can_edit", False)
    )
    
    await storage.set_page_permission(permission_data)
    
    await send_success(websocket, "page_shared", {
        "page_id": page_id,
        "subject_type": permission_data.subject_type.value,
        "subject_id": permission_data.subject_id
    })
