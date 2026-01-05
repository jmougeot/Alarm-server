Parfait. Voici **LA PIPELINE COMPLÈTE, DE BOUT EN BOUT**, incluant **stockage de données**, **déploiement gratuit**, et **évolutivité**, exactement adaptée à ton projet.

Je vais te la donner :

* **dans l’ordre chronologique**
* avec **ce que tu fais concrètement**
* et **pourquoi chaque étape existe**

---

# 🎯 OBJECTIF FINAL

Un **serveur d’alarmes** :

* WebSocket (temps réel)
* stockage persistant des alarmes + utilisateurs
* auth robuste (quand activée)
* déployé gratuitement (Fly.io)
* portable vers un VPS
* sans admin système

---

# 🧠 VUE D’ENSEMBLE (PIPELINE)

```
1. Code serveur
2. Architecture propre
3. Stockage abstrait
4. Stockage persistant (SQLite async)
5. Docker
6. Test local
7. Déploiement Fly.io (gratuit)
8. Connexion clients Qt
9. Sécurité progressive
10. Migration possible (VPS)
```

---

# 1️⃣ CRÉER LE REPO `alarm-server`

### Structure finale

```text
alarm-server/
├── app/
│   ├── main.py        # Entrée FastAPI
│   ├── ws.py          # Logique WebSocket
│   ├── models.py      # Modèles de données
│   ├── storage.py     # Accès DB (async)
│   └── auth.py        # Auth (optionnel)
├── requirements.txt
├── Dockerfile
├── README.md
└── .gitignore
```

---

# 2️⃣ ÉCRIRE LE SERVEUR (LOGIQUE)

### Règles strictes

* ❌ pas de Bloomberg
* ❌ pas d’UI
* ❌ pas de logique métier trading
* ✅ uniquement coordination & état partagé

---

# 3️⃣ MODÈLES DE DONNÉES (`models.py`)

Tu définis **le langage commun** :

* Alarm
* User
* Event (optionnel)

👉 Aucun accès DB ici.

---

# 4️⃣ STOCKAGE (ABSTRACTION) — `storage.py`

👉 **Point clé de toute la pipeline**

### Rôle

* centraliser tout accès aux données
* cacher le “comment” (mémoire, SQLite, Postgres…)

```
ws.py
  ↓
storage.py
  ↓
SQLite async
```

---

# 5️⃣ STOCKAGE PERSISTANT — SQLite ASYNC

### Pourquoi SQLite

* un seul fichier
* zéro serveur DB
* robuste
* parfait pour Fly.io / VPS
* backup trivial

### Tech

* `aiosqlite`
* async / await
* non bloquant

👉 Données persistantes :

* alarmes
* utilisateurs
* historique léger

---

# 6️⃣ AUTHENTIFICATION (PROGRESSIVE)

### Phase 1 — Token partagé

* rapide
* interne
* zéro DB user

### Phase 2 — Auth robuste

* endpoint `/login` (HTTP)
* bcrypt pour passwords
* JWT court
* WebSocket authentifié par token

👉 Les users sont stockés en DB (hashés).

---

# 7️⃣ DOCKERISATION (OBLIGATOIRE POUR FLY)

### Dockerfile

* Python slim
* dépendances
* uvicorn
* port 8080

👉 **Aucune logique Fly spécifique**.

Résultat :

```
docker run alarm-server
```

fonctionne partout.

---

# 8️⃣ TEST LOCAL COMPLET

### Sans Docker

```bash
uvicorn app.main:app --reload
```

### Avec Docker

```bash
docker build -t alarm-server .
docker run -p 8080:8080 alarm-server
```

👉 Si ça marche ici → ça marchera en prod.

---

# 9️⃣ DÉPLOIEMENT GRATUIT — FLY.IO

### Étapes

```bash
fly auth login
fly launch
fly deploy
```

### Résultat

```
wss://ton-app.fly.dev/ws
```

* HTTPS/WSS automatique
* infra gérée
* gratuit au début

---

# 🔐 10️⃣ DONNÉES PERSISTANTES SUR FLY.IO

### Important

Fly.io **redéploie des VM éphémères**.

👉 Pour SQLite :

* créer un **volume persistant**
* stocker `alarms.db` dessus

Sans ça → DB perdue au redeploy.

---

# 11️⃣ CONNEXION CLIENT QT

* QWebSocket
* reconnexion auto
* login (si activé)
* WS authentifié

👉 Chaque client :

* interroge Bloomberg localement
* déclenche l’alarme
* notifie le serveur

---

# 12️⃣ SÉCURITÉ (ÉTAT FINAL)

| Niveau    | Mécanisme          |
| --------- | ------------------ |
| Transport | WSS (TLS)          |
| Passwords | bcrypt             |
| Tokens    | JWT expirable      |
| Accès     | auth + permissions |
| DB        | non exposée        |
| Secrets   | variables env      |

---

# 13️⃣ BACKUP & ÉVOLUTION

### Backups

* copier le fichier SQLite
* snapshot volume Fly
* export DB

### Migration

Fly.io → VPS :

```bash
docker run alarm-server
```

👉 même image, même DB.

---

# 🧠 CHECKLIST FINALE

✅ repo séparé
✅ WebSocket
✅ stockage persistant
✅ async
✅ Docker
✅ gratuit
✅ sécurisé progressivement
✅ portable

---

# 🧠 PHRASE CLÉ À RETENIR

> **Le serveur est une brique d’infrastructure : simple, stateless côté logique, stateful côté données.**


