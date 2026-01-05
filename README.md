#  Alarm Server

Serveur de coordination d'alarmes en temps réel avec WebSocket, authentification JWT et permissions par pages.

---

##  Table des matières

- [Architecture](#-architecture)
- [Installation](#-installation)
- [Configuration](#-configuration)
- [Lancement](#-lancement)
- [API HTTP](#-api-http)
- [WebSocket](#-websocket)
- [Modèle de permissions](#-modèle-de-permissions)
- [Déploiement](#-déploiement)
- [Client Qt](#-client-qt)

---

## Architecture

```
alarm-server/
├── app/
│   ├── main.py        # Entrée FastAPI + endpoints
│   ├── ws.py          # WebSocket + broadcast ciblé
│   ├── models.py      # Modèles de données
│   ├── storage.py     # Couche DB SQLite async
│   └── auth.py        # Auth bcrypt + JWT
├── data/
│   └── alarms.db      # Base SQLite (créée auto)
├── requirements.txt
├── Dockerfile
└── fly.toml
```

### Base de données

| Table | Rôle |
|-------|------|
| `users` | Utilisateurs (password hashé bcrypt) |
| `groups` | Groupes (desk, équipe...) |
| `user_groups` | Association user ↔ groupe |
| `pages` | Conteneurs d'alarmes (unité de permission) |
| `page_permissions` | Qui peut voir/éditer une page |
| `alarms` | Alarmes (héritent des permissions de la page) |
| `alarm_events` | Historique des déclenchements |

---

##  Installation

### Prérequis

- Python 3.10+
- pip

### Installation locale

```bash
# Cloner le repo
git clone <repo-url>
cd alarm-server

# Créer un environnement virtuel (recommandé)
python -m venv venv
venv\Scripts\activate  # Windows
# source venv/bin/activate  # Linux/Mac

# Installer les dépendances
pip install -r requirements.txt

# ⚠️ Important : uvicorn[standard] est requis pour le support WebSocket
# Le requirements.txt l'inclut déjà
```

---

## ⚙️ Configuration

### Variables d'environnement

| Variable | Description | Défaut |
|----------|-------------|--------|
| `JWT_SECRET_KEY` | Clé secrète pour signer les JWT | `dev-secret-key-change-in-production` |
| `TOKEN_EXPIRE_MINUTES` | Durée de validité des tokens (minutes) | `60` |
| `PORT` | Port du serveur | `8080` |

### Fichier .env (optionnel)

```env
JWT_SECRET_KEY=ma-cle-secrete-ultra-longue
TOKEN_EXPIRE_MINUTES=120
PORT=8080
```

---

## Lancement

> ⚠️ **Note** : Le support WebSocket nécessite `uvicorn[standard]` (inclus dans requirements.txt)

### Mode développement

```bash
# Avec environnement virtuel activé
uvicorn app.main:app --reload --port 8080
```

### Mode production

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8080 
```

> **Note** : Avec WebSocket, utilisez `--workers 1` pour éviter les problèmes de routage des connexions

### Avec Docker

```bash
# Build
docker build -t alarm-server .

# Run
docker run -p 8080:8080 \
  -e JWT_SECRET_KEY=your-secret \
  -v alarm_data:/app/data \
  alarm-server
```

### Accès

- **API Docs** : http://localhost:8080/docs
- **Health check** : http://localhost:8080/health
- **WebSocket** : ws://localhost:8080/ws?token=<jwt>

---

## API HTTP

### Authentification

#### Créer un compte

```http
POST /register
Content-Type: application/json

{
  "username": "john",
  "password": "secret123"
}
```

**Réponse :**
```json
{
  "id": "uuid",
  "username": "john",
  "created_at": "2024-01-15T10:30:00"
}
```

#### Se connecter

```http
POST /login
Content-Type: application/x-www-form-urlencoded

username=john&password=secret123
```

**Réponse :**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer"
}
```

#### Info utilisateur courant

```http
GET /me
Authorization: Bearer <token>
```

---

### Groupes

#### Créer un groupe

```http
POST /groups
Authorization: Bearer <token>
Content-Type: application/json

{
  "name": "Desk Euro"
}
```

#### Ajouter un membre

```http
POST /groups/{group_id}/members/{user_id}
Authorization: Bearer <token>
```

---

### Pages

#### Créer une page

```http
POST /pages
Authorization: Bearer <token>
Content-Type: application/json

{
  "name": "Alarmes EUR/USD"
}
```

#### Lister mes pages

```http
GET /pages
Authorization: Bearer <token>
```

**Réponse :**
```json
[
  {
    "id": "uuid",
    "name": "Alarmes EUR/USD",
    "owner_id": "uuid",
    "is_owner": true
  }
]
```

---

## 🔗 WebSocket

### Connexion

```
ws://localhost:8080/ws?token=<jwt>
```

Le token JWT est obtenu via `POST /login`.

### Message initial (automatique)

À la connexion, le serveur envoie l'état complet :

```json
{
  "type": "initial_state",
  "payload": {
    "user": { "id": "uuid", "username": "john" },
    "pages": [
      { "id": "uuid", "name": "Page 1", "owner_id": "uuid", "is_owner": true }
    ],
    "alarms": [
      {
        "id": "uuid",
        "page_id": "uuid",
        "ticker": "EUR/USD",
        "option": "spot",
        "condition": "above",
        "active": true,
        "last_triggered": null
      }
    ]
  }
}
```

---

### Messages Client → Serveur

#### Créer une alarme

```json
{
  "type": "create_alarm",
  "payload": {
    "page_id": "uuid",
    "ticker": "EUR/USD",
    "option": "spot",
    "condition": "above"
  }
}
```

#### Modifier une alarme

```json
{
  "type": "update_alarm",
  "payload": {
    "alarm_id": "uuid",
    "ticker": "EUR/GBP",
    "active": false
  }
}
```

#### Supprimer une alarme

```json
{
  "type": "delete_alarm",
  "payload": {
    "alarm_id": "uuid"
  }
}
```

#### Déclencher une alarme

```json
{
  "type": "trigger_alarm",
  "payload": {
    "alarm_id": "uuid",
    "price": 1.0850
  }
}
```

#### Créer une page

```json
{
  "type": "create_page",
  "payload": {
    "name": "Mes nouvelles alarmes"
  }
}
```

#### Partager une page

```json
{
  "type": "share_page",
  "payload": {
    "page_id": "uuid",
    "subject_type": "user",
    "subject_id": "user-uuid",
    "can_view": true,
    "can_edit": false
  }
}
```

Ou partager avec un groupe :

```json
{
  "type": "share_page",
  "payload": {
    "page_id": "uuid",
    "subject_type": "group",
    "subject_id": "group-uuid",
    "can_view": true,
    "can_edit": true
  }
}
```

---

### Messages Serveur → Client

#### Mise à jour d'alarme (broadcast)

```json
{
  "type": "alarm_update",
  "payload": {
    "alarm_id": "uuid",
    "page_id": "uuid",
    "action": "created",
    "data": {
      "id": "uuid",
      "ticker": "EUR/USD",
      "option": "spot",
      "condition": "above",
      "active": true
    }
  }
}
```

Actions possibles : `created`, `updated`, `deleted`, `triggered`

#### Succès

```json
{
  "type": "success",
  "payload": {
    "action": "page_created",
    "data": { "id": "uuid", "name": "Ma page" }
  }
}
```

#### Erreur

```json
{
  "type": "error",
  "payload": {
    "message": "Permission denied: cannot edit this page"
  }
}
```

---

## 🔐 Modèle de permissions

### Principe clé

> **La page est l'unité de sécurité.**

- Une alarme appartient à UNE page
- Les permissions sont définies sur les pages, PAS sur les alarmes
- Le serveur filtre TOUT — le client ne reçoit que ce qu'il a le droit de voir

### Hiérarchie d'accès

1. **Owner** : accès total (view + edit + share)
2. **Permission user directe** : can_view / can_edit
3. **Permission groupe** : via les groupes de l'utilisateur

### Vérification des permissions

| Action | Permission requise |
|--------|-------------------|
| Voir les alarmes d'une page | `can_view` |
| Créer/modifier/supprimer une alarme | `can_edit` |
| Déclencher une alarme | `can_view` |
| Partager une page | Owner uniquement |

---

## ☁️ Déploiement

### Fly.io (gratuit)

```bash
# Installer Fly CLI
powershell -Command "iwr https://fly.io/install.ps1 -useb | iex"

# Se connecter
fly auth login

# Créer le volume persistant (1 Go)
fly volumes create alarm_data --size 1 --region cdg

# Définir le secret JWT
fly secrets set JWT_SECRET_KEY=votre-cle-secrete-de-production

# Déployer
fly deploy
```

**Résultat :**
```
wss://alarm-server.fly.dev/ws?token=<jwt>
```

### VPS / Docker

```bash
# Sur le serveur
docker pull ghcr.io/your-org/alarm-server:latest

docker run -d \
  --name alarm-server \
  --restart always \
  -p 8080:8080 \
  -e JWT_SECRET_KEY=your-secret \
  -v /data/alarm-server:/app/data \
  alarm-server
```

Avec reverse proxy (nginx/caddy) pour HTTPS.

---

## 🖥 Client Qt

### Exemple de connexion (C++ / Qt)

```cpp
#include <QWebSocket>
#include <QJsonDocument>
#include <QJsonObject>

class AlarmClient : public QObject {
    Q_OBJECT
    
public:
    AlarmClient(const QString& serverUrl, const QString& token)
        : m_socket(new QWebSocket())
    {
        connect(m_socket, &QWebSocket::connected, this, &AlarmClient::onConnected);
        connect(m_socket, &QWebSocket::textMessageReceived, this, &AlarmClient::onMessage);
        connect(m_socket, &QWebSocket::disconnected, this, &AlarmClient::onDisconnected);
        
        // Connexion avec token
        QUrl url(serverUrl + "?token=" + token);
        m_socket->open(url);
    }
    
private slots:
    void onConnected() {
        qDebug() << "Connected to alarm server";
    }
    
    void onMessage(const QString& message) {
        QJsonDocument doc = QJsonDocument::fromJson(message.toUtf8());
        QJsonObject obj = doc.object();
        
        QString type = obj["type"].toString();
        QJsonObject payload = obj["payload"].toObject();
        
        if (type == "initial_state") {
            // Charger l'état initial
            handleInitialState(payload);
        }
        else if (type == "alarm_update") {
            // Mettre à jour une alarme
            handleAlarmUpdate(payload);
        }
    }
    
    void triggerAlarm(const QString& alarmId, double price) {
        QJsonObject msg;
        msg["type"] = "trigger_alarm";
        
        QJsonObject payload;
        payload["alarm_id"] = alarmId;
        payload["price"] = price;
        msg["payload"] = payload;
        
        m_socket->sendTextMessage(
            QJsonDocument(msg).toJson(QJsonDocument::Compact)
        );
    }
    
private:
    QWebSocket* m_socket;
};
```

### Flow d'authentification

1. `POST /login` → récupérer le token
2. Ouvrir WebSocket avec `?token=<jwt>`
3. Recevoir `initial_state`
4. Envoyer/recevoir des messages

### Reconnexion automatique

```cpp
void onDisconnected() {
    // Retry après 5 secondes
    QTimer::singleShot(5000, this, [this]() {
        m_socket->open(m_url);
    });
}
```

---

## 📊 Sécurité

| Couche | Mécanisme |
|--------|-----------|
| Transport | WSS (TLS) en production |
| Passwords | bcrypt (hashés en DB) |
| Tokens | JWT avec expiration |
| Accès | Permissions par page |
| DB | Non exposée, fichier local |
| Secrets | Variables d'environnement |

---

## 🔧 Développement

### Lancer les tests

```bash
pytest tests/ -v
```

### Logs

Le serveur log les connexions/déconnexions WebSocket.

### Debug

```bash
# Mode verbose
uvicorn app.main:app --reload --log-level debug
```

---

## 📝 License

MIT


