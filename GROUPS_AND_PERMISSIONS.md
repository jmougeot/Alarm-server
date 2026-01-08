# Documentation : Gestion des Groupes et Permissions

Ce document décrit le fonctionnement du sistema de groupes, de permissions et de partage de pages dans l'application Alarm Server.

## 1. Concepts de Base

### Utilisateurs (`User`)
Chaque utilisateur est identifié par un ID unique et un nom d'utilisateur.
- Un utilisateur peut créer des **Pages**.
- Un utilisateur peut créer des **Groupes**.
- Un utilisateur peut être membre de plusieurs groupes.

### Pages (`Page`)
Une page est un espace contenant des alarmes.
- **Propriétaire (`Owner`)** : L'utilisateur qui a créé la page. Il a tous les droits sur celle-ci (voir, éditer, supprimer, gérer les permissions).
- **Accès** : L'accès à une page est régi par des permissions.

### Groupes (`Group`)
Un groupe est un ensemble d'utilisateurs.
- Sert à simplifier le partage de pages (on partage à un groupe au lieu de chaque utilisateur individuellement).
- Le créateur du groupe en est membre automatiquement.
- On peut ajouter ou retirer des membres d'un groupe.

---

## 2. Système de Permissions

Les permissions sont stockées dans la table `page_permissions`.

### Structure d'une permission
Une permission lie une **Page** à un **Sujet** (Utilisateur ou Groupe).

| Champ | Description |
|-------|-------------|
| `page_id` | L'ID de la page concernée |
| `subject_type` | `'user'` ou `'group'` |
| `subject_id` | L'ID de l'utilisateur ou du groupe |
| `can_view` | `1` (Vrai) ou `0` (Faux) |
| `can_edit` | `1` (Vrai) ou `0` (Faux) |

### Résolution des accès
Lorsqu'on vérifie si un utilisateur a accès à une page, le système vérifie :
1. **Est-il le propriétaire ?** -> Si OUI, accès total (View + Edit).
2. **A-t-il une permission directe ?** -> Vérifie la table pour `subject_type='user'` et `subject_id=user_id`.
3. **Est-il membre d'un groupe ayant la permission ?** -> Vérifie la table pour `subject_type='group'` et tous les `group_id` dont l'utilisateur est membre.
   - *Note : Les permissions sont cumulatives. Si un groupe donne accès en lecture, l'utilisateur a accès en lecture.*

---

## 3. Fonctionnement des APIs

### Gestion des Groupes (HTTP)

- **Créer un groupe** : `POST /groups`
  - Crée le groupe et ajoute le créateur comme premier membre.
- **Ajouter un membre** : `POST /groups/{group_id}/members/{user_id}`
- **Retirer un membre** : `DELETE /groups/{group_id}/members/{user_id}`
- **Lister mes groupes** : `GET /groups`
- **Voir les détails d'un groupe** : `GET /groups/{group_id}`

### Partage de Pages (HTTP & WebSocket)

Seul le propriétaire (`owner`) d'une page peut gérer ses permissions.

- **Voir les permissions** : `GET /pages/{page_id}/permissions`
- **Ajouter/Modifier une permission** : `POST /pages/{page_id}/permissions`
  - Body :
    ```json
    {
      "subject_type": "user",  // ou "group"
      "subject_id": "...",
      "can_view": true,
      "can_edit": false
    }
    ```
- **Retirer une permission** : `DELETE /pages/{page_id}/permissions?subject_type=...&subject_id=...`

### WebSocket - Temps Réel

Le serveur utilise les permissions pour filtrer les messages en temps réel.

1. **Broadcast ciblé (`broadcast_to_page_users`)** :
   - Quand une alarme change sur une page (`create`, `update`, `delete`, `trigger`).
   - Le serveur calcule la liste de **tous les utilisateurs** ayant accès à cette page (propriétaire + permissions directes + membres des groupes autorisés).
   - Le message WebSocket est envoyé **uniquement** à ces utilisateurs connectés.

2. **Actions via WebSocket** :
   - `create_alarm`, `update_alarm`, `delete_alarm` : Le serveur vérifie d'abord si l'utilisateur a la permission **Edit (`can_edit`)** sur la page concernée avant d'accepter l'action.

---

## 4. Scénarios d'Utilisation

### Scénario A : Partage Simple
1. Alice crée la "Page Trading". Elle en est `owner`.
2. Alice veut que Bob puisse voir les alarmes.
3. Alice ajoute une permission : `subject_type='user', subject_id=Bob, can_view=true`.
4. Bob voit "Page Trading" dans sa liste. Il reçoit les mises à jour des alarmes.
5. Bob essaie de modifier une alarme -> **Refusé** (pas de `can_edit`).

### Scénario B : Équipe de Trading (Groupes)
1. Alice crée le groupe "Team Alpha".
2. Alice ajoute Bob et Charlie dans "Team Alpha".
3. Alice crée la "Page Forex".
4. Alice partage la page au groupe : `subject_type='group', subject_id=TeamAlpha, can_view=true, can_edit=true`.
5. Résultat :
   - Bob et Charlie voient la page.
   - Bob et Charlie peuvent ajouter/modifier des alarmes sur cette page.
   - Si Dave rejoint "Team Alpha" plus tard, il aura accès automatiquement.
   - Si Bob quitte le groupe, il perd l'accès immédiatement.
