#  PLAN GLOBAL DE LA DB

```
users
groups
user_groups

pages
page_permissions

alarms
alarm_events
```

 **Principe clé** :

* les **pages portent les permissions**
* les **alarmes héritent des pages**
* le serveur fait TOUS les filtres

---

# `users`

```sql
users (
  id TEXT PRIMARY KEY,              -- UUID
  username TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  created_at DATETIME NOT NULL
)
```

🔹 Un utilisateur = une identité
🔹 Aucun mot de passe en clair

---

# `groups`

```sql
groups (
  id TEXT PRIMARY KEY,              -- UUID
  name TEXT UNIQUE NOT NULL
)
```

🔹 Desk, équipe, projet, etc.

---

# `user_groups`

```sql
user_groups (
  user_id TEXT NOT NULL,
  group_id TEXT NOT NULL,
  PRIMARY KEY (user_id, group_id),
  FOREIGN KEY (user_id) REFERENCES users(id),
  FOREIGN KEY (group_id) REFERENCES groups(id)
)
```

🔹 Un user peut appartenir à plusieurs groupes
🔹 Un groupe a plusieurs users

---

# `pages`  **(UNITÉ CENTRALE)**

```sql
pages (
  id TEXT PRIMARY KEY,              -- UUID
  name TEXT NOT NULL,
  owner_id TEXT NOT NULL,
  created_at DATETIME NOT NULL,

  FOREIGN KEY (owner_id) REFERENCES users(id)
)
```

🔹 Une page :

* appartient à un owner
* contient plusieurs alarmes
* définit le périmètre de visibilité

---

# `page_permissions`  **(TABLE CLÉ)**

```sql
page_permissions (
  page_id TEXT NOT NULL,
  subject_type TEXT NOT NULL CHECK(subject_type IN ('user', 'group')),
  subject_id TEXT NOT NULL,

  can_view INTEGER NOT NULL DEFAULT 1,
  can_edit INTEGER NOT NULL DEFAULT 0,

  PRIMARY KEY (page_id, subject_type, subject_id),
  FOREIGN KEY (page_id) REFERENCES pages(id)
)
```

🔹 Définit **QUI voit / édite la page**
🔹 `subject_id` → `users.id` OU `groups.id`

**Si tu as accès à la page, tu as accès à TOUTES ses alarmes**

---

# `alarms`

```sql
alarms (
  id TEXT PRIMARY KEY,              -- UUID
  page_id TEXT NOT NULL,

  ticker TEXT NOT NULL,
  option TEXT NOT NULL,
  condition TEXT NOT NULL,

  created_by TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 1,

  created_at DATETIME NOT NULL,
  last_triggered DATETIME,

  FOREIGN KEY (page_id) REFERENCES pages(id),
  FOREIGN KEY (created_by) REFERENCES users(id)
)
```

🔹 Une alarme :

* appartient à UNE page
* hérite des permissions de la page
* n’a PAS de permissions propres

---

# `alarm_events` (historique / audit)

```sql
alarm_events (
  id TEXT PRIMARY KEY,              -- UUID
  alarm_id TEXT NOT NULL,
  triggered_by TEXT NOT NULL,

  price REAL,
  triggered_at DATETIME NOT NULL,

  FOREIGN KEY (alarm_id) REFERENCES alarms(id),
  FOREIGN KEY (triggered_by) REFERENCES users(id)
)
```

# TEMPS RÉEL : LIEN DB ↔ WEBSOCKET

### À la connexion WS

* identifier `user_id`
* charger :

  * pages accessibles
  * groupes du user

---

### Lors d’une modification d’alarme

1. UPDATE DB
2. SELECT users autorisés sur la page
3. PUSH WS ciblé à ces users

---

#  REQUÊTES CLÉS (conceptuelles)

### Pages visibles par un user

```sql
pages
JOIN page_permissions
WHERE
  subject_type = 'user' AND subject_id = :user_id
  OR
  subject_type = 'group' AND subject_id IN (:group_ids)
  OR
  pages.owner_id = :user_id
```

---

### Alarmes visibles

```sql
SELECT * FROM alarms
WHERE page_id IN (:page_ids)
```

---
