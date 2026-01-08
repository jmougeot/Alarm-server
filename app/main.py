"""
Main Entry Point — FastAPI + WebSocket Server
Serveur d'alarmes avec sécurité niveau final
"""

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware

from .models import User, UserCreate, Token, GroupCreate, PageCreate, PagePermissionCreate, PagePermissionRequest
from .ws import manager, handle_message, WSMessage
from . import storage, auth


# ─────────────────────────────────────────────────────────────
# LIFESPAN (startup/shutdown)
# ─────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialisation au démarrage"""
    # Créer le dossier data si nécessaire
    Path("data").mkdir(exist_ok=True)
    
    # Initialiser la base de données
    await storage.init_db()
    
    print("🚀 Alarm Server started")
    print("📂 Database initialized at data/alarms.db")
    
    yield
    
    print("👋 Alarm Server stopped")


# ─────────────────────────────────────────────────────────────
# APPLICATION
# ─────────────────────────────────────────────────────────────

app = FastAPI(
    title="Alarm Server",
    description="WebSocket-based alarm coordination server with permissions",
    version="1.0.0",
    lifespan=lifespan
)

# CORS (pour dev local)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # En prod, restreindre
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─────────────────────────────────────────────────────────────
# HEALTH CHECK
# ─────────────────────────────────────────────────────────────

@app.get("/health")
async def health_check():
    """Health check pour monitoring"""
    return {"status": "healthy"}


# ─────────────────────────────────────────────────────────────
# AUTH ENDPOINTS (HTTP)
# ─────────────────────────────────────────────────────────────

@app.post("/register", response_model=User)
async def register(user_data: UserCreate):
    """Enregistre un nouvel utilisateur"""
    return await auth.register_user(user_data)


@app.post("/login", response_model=Token)
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    """
    Authentifie un utilisateur et retourne un JWT
    Le token sera utilisé pour la connexion WebSocket
    """
    user = await auth.authenticate_user(form_data.username, form_data.password)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    access_token = auth.create_access_token(user.id, user.username)
    
    return Token(access_token=access_token)


@app.get("/me", response_model=User)
async def get_current_user_info(current_user: User = Depends(auth.get_current_user)):
    """Retourne les infos de l'utilisateur connecté"""
    return current_user


# ─────────────────────────────────────────────────────────────
# GROUPS (HTTP)
# ─────────────────────────────────────────────────────────────

@app.post("/groups", response_model=dict)
async def create_group(
    group_data: GroupCreate,
    current_user: User = Depends(auth.get_current_user)
):
    """Crée un nouveau groupe"""
    # Vérifier si le groupe existe déjà
    existing = await storage.get_group_by_name(group_data.name)
    if existing:
        raise HTTPException(status_code=400, detail="Group name already exists")
    
    group = await storage.create_group(group_data)
    
    # Ajouter automatiquement le créateur comme membre
    await storage.add_user_to_group(current_user.id, group.id)
    
    return {"id": group.id, "name": group.name}


@app.post("/groups/{group_id}/members/{user_id}")
async def add_member_to_group(
    group_id: str,
    user_id: str,
    current_user: User = Depends(auth.get_current_user)
):
    """Ajoute un membre à un groupe"""
    success = await storage.add_user_to_group(user_id, group_id)
    if not success:
        raise HTTPException(status_code=400, detail="Could not add user to group")
    
    # Récupérer les infos du groupe
    group = await storage.get_group_by_id(group_id)
    
    # Notifier le nouvel utilisateur des pages partagées avec ce groupe
    pages_shared = await storage.get_pages_shared_with_group(group_id)
    
    for page in pages_shared:
        # Récupérer le nom du propriétaire
        owner = await storage.get_user_by_id(page.owner_id)
        owner_name = owner.username if owner else None
        
        # Récupérer les alarmes de la page
        alarms = await storage.get_alarms_for_pages([page.id])
        
        # Récupérer les droits d'édition pour ce groupe
        can_edit = await storage.get_group_permission_on_page(group_id, page.id)
        
        # Envoyer la page et ses alarmes au nouvel utilisateur du groupe
        await manager.send_to_user(user_id, WSMessage(
            type="page_shared_with_you",
            payload={
                "page": {
                    "id": page.id,
                    "name": page.name,
                    "owner_id": page.owner_id,
                    "owner_name": owner_name,
                    "is_owner": False,
                    "group_id": group.id if group else None,
                    "group_name": group.name if group else None,
                    "shared_by": None,
                    "can_edit": can_edit
                },
                "alarms": [
                    {
                        "id": a.id,
                        "page_id": a.page_id,
                        "ticker": a.ticker,
                        "option": a.option,
                        "condition": a.condition.value if hasattr(a.condition, 'value') else a.condition,
                        "active": a.active,
                        "last_triggered": a.last_triggered.isoformat() if a.last_triggered else None,
                        "strategy_id": a.strategy_id,
                        "strategy_name": a.strategy_name,
                        "leg_index": a.leg_index,
                        "position": a.position,
                        "quantity": a.quantity,
                        "client": a.client,
                        "action": a.action
                    }
                    for a in alarms
                ]
            }
        ))
    
    return {"status": "added"}


@app.get("/users/search")
async def search_user(
    username: str,
    current_user: User = Depends(auth.get_current_user)
):
    """Recherche un utilisateur par nom"""
    user_data = await storage.get_user_by_username(username)
    if not user_data:
        raise HTTPException(status_code=404, detail="User not found")
    
    return {
        "id": user_data["id"],
        "username": user_data["username"]
    }


@app.get("/groups/search")
async def search_group(
    name: str,
    current_user: User = Depends(auth.get_current_user)
):
    """Recherche un groupe par nom"""
    group = await storage.get_group_by_name(name)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    
    return {
        "id": group.id,
        "name": group.name
    }


@app.get("/groups/{group_id}")
async def get_group(
    group_id: str,
    current_user: User = Depends(auth.get_current_user)
):
    """Obtient les détails d'un groupe"""
    group = await storage.get_group_by_id(group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    
    # Vérifier que l'utilisateur est membre
    is_member = await storage.is_user_in_group(current_user.id, group_id)
    if not is_member:
        raise HTTPException(status_code=403, detail="Not a member of this group")
    
    members = await storage.get_group_members(group_id)
    
    return {
        "id": group.id,
        "name": group.name,
        "members": [{"id": m.id, "username": m.username} for m in members]
    }


@app.get("/groups")
async def list_my_groups(
    current_user: User = Depends(auth.get_current_user)
):
    """Liste les groupes de l'utilisateur"""
    groups = await storage.get_user_groups_full(current_user.id)
    return [{"id": g.id, "name": g.name} for g in groups]


@app.delete("/groups/{group_id}")
async def delete_group(
    group_id: str,
    current_user: User = Depends(auth.get_current_user)
):
    """Supprime un groupe (créateur seulement - simplifié ici)"""
    group = await storage.get_group_by_id(group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    
    await storage.delete_group(group_id)
    return {"status": "deleted"}


@app.delete("/groups/{group_id}/members/{user_id}")
async def remove_group_member(
    group_id: str,
    user_id: str,
    current_user: User = Depends(auth.get_current_user)
):
    """Retire un membre d'un groupe"""
    group = await storage.get_group_by_id(group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    
    success = await storage.remove_user_from_group(user_id, group_id)
    if not success:
        raise HTTPException(status_code=400, detail="Could not remove user from group")
    
    return {"status": "removed"}


# ─────────────────────────────────────────────────────────────
# PAGES (HTTP)
# ─────────────────────────────────────────────────────────────

@app.post("/pages", response_model=dict)
async def create_page(
    page_data: PageCreate,
    current_user: User = Depends(auth.get_current_user)
):
    """Crée une nouvelle page"""
    page = await storage.create_page(page_data, current_user.id)
    
    # Notifier le client via WebSocket (multi-device sync)
    from .models import WSMessage
    page_update = WSMessage(
        type="page_created",
        payload={
            "id": page.id,
            "name": page.name,
            "owner_id": page.owner_id,
            "owner_name": current_user.username,
            "is_owner": True,
            "group_id": None,
            "group_name": None,
            "shared_by": None,
            "can_edit": True
        }
    )
    await manager.send_to_user(current_user.id, page_update)
    
    return {
        "id": page.id,
        "name": page.name,
        "owner_id": page.owner_id,
        "owner_name": current_user.username,
        "is_owner": True,
        "group_id": None,
        "group_name": None,
        "shared_by": None,
        "can_edit": True
    }


@app.get("/pages")
async def list_pages(current_user: User = Depends(auth.get_current_user)):
    """Liste les pages accessibles par l'utilisateur avec métadonnées enrichies"""
    pages = await storage.get_accessible_pages_enriched(current_user.id)
    return pages


@app.delete("/pages/{page_id}")
async def delete_page(
    page_id: str,
    current_user: User = Depends(auth.get_current_user)
):
    """Supprime une page (seul l'owner peut supprimer)"""
    page = await storage.get_page_by_id(page_id)
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")
    
    # Seul l'owner peut supprimer
    if page.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only owner can delete page")
    
    success = await storage.delete_page(page_id)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to delete page")
    
    return {"status": "deleted", "page_id": page_id}


@app.get("/pages/{page_id}/permissions")
async def get_page_permissions(
    page_id: str,
    current_user: User = Depends(auth.get_current_user)
):
    """Liste les permissions d'une page"""
    page = await storage.get_page_by_id(page_id)
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")
    
    # Vérifier que l'utilisateur a accès
    can_view = await storage.can_user_view_page(current_user.id, page_id)
    if not can_view:
        raise HTTPException(status_code=403, detail="Access denied")
    
    permissions = await storage.get_page_permissions_list(page_id)
    
    # Enrichir avec les noms
    result = []
    for perm in permissions:
        if perm["subject_type"] == "user":
            user = await storage.get_user_by_id(perm["subject_id"])
            subject_name = user.username if user else "Unknown"
        else:
            group = await storage.get_group_by_id(perm["subject_id"])
            subject_name = group.name if group else "Unknown"
        
        result.append({
            "subject_type": perm["subject_type"],
            "subject_id": perm["subject_id"],
            "subject_name": subject_name,
            "can_view": perm["can_view"],
            "can_edit": perm["can_edit"]
        })
    
    return result


@app.post("/pages/{page_id}/permissions")
async def add_page_permission(
    page_id: str,
    permission_data: PagePermissionRequest,
    current_user: User = Depends(auth.get_current_user)
):
    """Ajoute ou modifie une permission sur une page"""
    page = await storage.get_page_by_id(page_id)
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")
    
    # Seul l'owner peut gérer les permissions
    if page.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only owner can manage permissions")
    
    # Créer le PagePermissionCreate avec le page_id de l'URL
    perm_create = PagePermissionCreate(
        page_id=page_id,
        subject_type=permission_data.subject_type,
        subject_id=permission_data.subject_id,
        can_view=permission_data.can_view,
        can_edit=permission_data.can_edit
    )
    
    permission = await storage.set_page_permission(perm_create)
    
    # Notifier les utilisateurs concernés par le nouveau partage
    from .models import WSMessage, SubjectType
    
    # Récupérer les infos du groupe si partage avec un groupe
    group_id = None
    group_name = None
    if permission_data.subject_type == SubjectType.GROUP:
        group = await storage.get_group_by_id(permission_data.subject_id)
        if group:
            group_id = group.id
            group_name = group.name
    
    # Récupérer le nom du propriétaire
    owner = await storage.get_user_by_id(page.owner_id)
    owner_name = owner.username if owner else None
    
    # Récupérer les alarmes de la page
    alarms = await storage.get_alarms_for_pages([page_id])
    
    # Construire le payload enrichi de la page
    page_payload = {
        "id": page.id,
        "name": page.name,
        "owner_id": page.owner_id,
        "owner_name": owner_name,
        "is_owner": False,
        "group_id": group_id,
        "group_name": group_name,
        "shared_by": owner_name if permission_data.subject_type == SubjectType.USER else None,
        "can_edit": permission_data.can_edit
    }
    
    page_shared_message = WSMessage(
        type="page_shared_with_you",
        payload={
            "page": page_payload,
            "alarms": [
                {
                    "id": a.id,
                    "page_id": a.page_id,
                    "ticker": a.ticker,
                    "option": a.option,
                    "condition": a.condition.value if hasattr(a.condition, 'value') else a.condition,
                    "active": a.active,
                    "last_triggered": a.last_triggered.isoformat() if a.last_triggered else None,
                    "strategy_id": a.strategy_id,
                    "strategy_name": a.strategy_name,
                    "leg_index": a.leg_index,
                    "position": a.position,
                    "quantity": a.quantity,
                    "client": a.client,
                    "action": a.action
                }
                for a in alarms
            ]
        }
    )
    
    if permission_data.subject_type == SubjectType.USER:
        # Partage avec un user - lui envoyer la page
        await manager.send_to_user(permission_data.subject_id, page_shared_message)
    elif permission_data.subject_type == SubjectType.GROUP:
        # Partage avec un groupe - envoyer à tous les membres du groupe
        group_members = await storage.get_group_members(permission_data.subject_id)
        for member in group_members:
            # Ne pas renvoyer au owner (il a déjà la page)
            if member.id != current_user.id:
                await manager.send_to_user(member.id, page_shared_message)
    
    return {
        "subject_type": permission.subject_type.value,
        "subject_id": permission.subject_id,
        "can_view": permission.can_view,
        "can_edit": permission.can_edit
    }


@app.delete("/pages/{page_id}/permissions")
async def remove_page_permission(
    page_id: str,
    subject_type: str,
    subject_id: str,
    current_user: User = Depends(auth.get_current_user)
):
    """Retire une permission d'une page"""
    from .models import WSMessage, SubjectType
    
    page = await storage.get_page_by_id(page_id)
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")
    
    # Seul l'owner peut retirer des permissions
    if page.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only owner can manage permissions")
    
    # Récupérer les users à notifier AVANT de supprimer la permission
    users_to_notify = []
    if subject_type == "user":
        users_to_notify = [subject_id]
    elif subject_type == "group":
        group_members = await storage.get_group_members(subject_id)
        users_to_notify = [m.id for m in group_members if m.id != current_user.id]
    
    success = await storage.remove_page_permission(page_id, subject_type, subject_id)
    if not success:
        raise HTTPException(status_code=404, detail="Permission not found")
    
    # Notifier les utilisateurs qui ont perdu l'accès
    permission_removed_message = WSMessage(
        type="page_access_revoked",
        payload={"page_id": page_id}
    )
    
    for user_id in users_to_notify:
        # Vérifier si l'user a encore accès via d'autres permissions
        still_has_access = await storage.can_user_view_page(user_id, page_id)
        if not still_has_access:
            await manager.send_to_user(user_id, permission_removed_message)
    
    return {"status": "removed"}


# ─────────────────────────────────────────────────────────────
# WEBSOCKET ENDPOINT
# ─────────────────────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    Point d'entrée WebSocket principal
    
    Connexion : ws://host/ws?token=<jwt>
    
    Le token est obtenu via POST /login
    """
    # Récupérer le token depuis les query params
    token = websocket.query_params.get("token")
    
    # Authentification obligatoire
    if not token:
        await websocket.close(code=4001, reason="Token required")
        return
    
    user = await auth.authenticate_ws_token(token)
    
    if not user:
        await websocket.close(code=4001, reason="Invalid token")
        return
    
    # Connexion acceptée
    try:
        await manager.connect(websocket, user)
    except Exception as e:
        print(f"[WS ERROR] Failed to connect user {user.username}: {e}")
        import traceback
        traceback.print_exc()
        try:
            await websocket.close(code=1011, reason="Connection setup failed")
        except Exception:
            pass
        return
    
    try:
        while True:
            # Recevoir les messages avec timeout pour détecter connexions mortes
            try:
                data = await websocket.receive_json()
            except ValueError as json_err:
                # JSON invalide - envoyer erreur mais continuer
                print(f"[WS ERROR] Invalid JSON from {user.username}: {json_err}")
                continue
            
            # Traiter le message
            try:
                await handle_message(websocket, user, data)
            except Exception as handler_err:
                print(f"[WS ERROR] Handler error for {user.username}: {handler_err}")
                import traceback
                traceback.print_exc()
                # Continuer la boucle, ne pas fermer la connexion
            
    except WebSocketDisconnect:
        pass  # Déconnexion normale
    except Exception as e:
        print(f"[WS ERROR] Unexpected error for user {user.username}: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Toujours nettoyer la connexion
        manager.disconnect(websocket)


# ─────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    
    port = int(os.getenv("PORT", "8080"))
    
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=port,
        reload=True
    )
