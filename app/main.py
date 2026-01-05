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

from .models import User, UserCreate, Token, GroupCreate, PageCreate
from . import storage, auth
from .ws import manager, handle_message


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
    group = await storage.create_group(group_data)
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
    return {"status": "added"}


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
    return {
        "id": page.id,
        "name": page.name,
        "owner_id": page.owner_id
    }


@app.get("/pages")
async def list_pages(current_user: User = Depends(auth.get_current_user)):
    """Liste les pages accessibles par l'utilisateur"""
    pages = await storage.get_accessible_pages(current_user.id)
    return [
        {
            "id": p.id,
            "name": p.name,
            "owner_id": p.owner_id,
            "is_owner": p.owner_id == current_user.id
        }
        for p in pages
    ]


# ─────────────────────────────────────────────────────────────
# WEBSOCKET ENDPOINT
# ─────────────────────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str = None):
    """
    Point d'entrée WebSocket principal
    
    Connexion : ws://host/ws?token=<jwt>
    
    Le token est obtenu via POST /login
    """
    # Authentification obligatoire
    if not token:
        await websocket.close(code=4001, reason="Token required")
        return
    
    user = await auth.authenticate_ws_token(token)
    
    if not user:
        await websocket.close(code=4001, reason="Invalid token")
        return
    
    # Connexion acceptée
    await manager.connect(websocket, user)
    
    try:
        while True:
            # Recevoir les messages
            data = await websocket.receive_json()
            
            # Traiter le message
            await handle_message(websocket, user, data)
            
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        print(f"WebSocket error for user {user.username}: {e}")
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
