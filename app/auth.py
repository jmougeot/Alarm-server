"""
Auth Layer — Authentification robuste (bcrypt + JWT)
Sécurité niveau final : passwords hashés, tokens expirables
"""

import os
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from passlib.context import CryptContext

from .models import User, UserCreate, TokenData
from . import storage


# ─────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────

# Secrets (en production, utiliser des variables d'environnement)
SECRET_KEY = os.getenv("JWT_SECRET_KEY", "dev-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("TOKEN_EXPIRE_MINUTES", "60"))

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# HTTP Bearer token
security = HTTPBearer()


# ─────────────────────────────────────────────────────────────
# PASSWORD UTILS
# ─────────────────────────────────────────────────────────────

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Vérifie un mot de passe contre son hash"""
    return pwd_context.verify(plain_password, hashed_password)


def hash_password(password: str) -> str:
    """Hash un mot de passe avec bcrypt"""
    return pwd_context.hash(password)


# ─────────────────────────────────────────────────────────────
# JWT UTILS
# ─────────────────────────────────────────────────────────────

def create_access_token(user_id: str, username: str, expires_delta: Optional[timedelta] = None) -> str:
    """Crée un JWT avec expiration"""
    expire = datetime.now() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    
    to_encode = {
        "sub": user_id,
        "username": username,
        "exp": expire
    }
    
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[TokenData]:
    """Décode et valide un JWT"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        username: str = payload.get("username")
        
        if user_id is None or username is None:
            return None
        
        return TokenData(user_id=user_id, username=username)
    except JWTError:
        return None


# ─────────────────────────────────────────────────────────────
# AUTH OPERATIONS
# ─────────────────────────────────────────────────────────────

async def register_user(user_data: UserCreate) -> User:
    """Enregistre un nouvel utilisateur"""
    # Vérifier si l'utilisateur existe déjà
    existing = await storage.get_user_by_username(user_data.username)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already registered"
        )
    
    # Hasher le mot de passe
    password_hash = hash_password(user_data.password)
    
    # Créer l'utilisateur
    return await storage.create_user(user_data, password_hash)


async def authenticate_user(username: str, password: str) -> Optional[User]:
    """Authentifie un utilisateur"""
    user_data = await storage.get_user_by_username(username)
    
    if not user_data:
        return None
    
    if not verify_password(password, user_data["password_hash"]):
        return None
    
    return User(
        id=user_data["id"],
        username=user_data["username"],
        created_at=user_data["created_at"]
    )


# ─────────────────────────────────────────────────────────────
# DEPENDENCIES (FastAPI)
# ─────────────────────────────────────────────────────────────

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> User:
    """Dépendance FastAPI : récupère l'utilisateur courant depuis le token"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    token_data = decode_token(credentials.credentials)
    if token_data is None:
        raise credentials_exception
    
    user = await storage.get_user_by_id(token_data.user_id)
    if user is None:
        raise credentials_exception
    
    return user


# ─────────────────────────────────────────────────────────────
# WEBSOCKET AUTH
# ─────────────────────────────────────────────────────────────

async def authenticate_ws_token(token: str) -> Optional[User]:
    """
    Authentifie un token WebSocket
    Utilisé lors de la connexion WS
    """
    token_data = decode_token(token)
    if token_data is None:
        return None
    
    return await storage.get_user_by_id(token_data.user_id)
