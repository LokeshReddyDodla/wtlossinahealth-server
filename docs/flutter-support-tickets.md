# Flutter integration — Support Tickets

This is everything the **patient app** and **care provider app** need to
wire up the new support-ticket feature. Backend lives on branch
`feat/support-tickets`; once merged to `main` the endpoints are live.

> **TL;DR**: A support ticket is just a chat with `kind == "support"`. All
> the messaging machinery you already use (Socket.IO, send_message,
> get_messages, attachments) works unchanged — you just add a ticket
> create/list/status surface on top.

---

## 1. Mandatory: register a new Android notification channel

Both apps must register a channel with id `support_messages` before the
first support FCM lands, otherwise Android drops the notification or
shows it in a grey "Misc" bucket.

```dart
// Android: lib/notifications/channels.dart (or wherever you set channels up)
const supportChannel = AndroidNotificationChannel(
  'support_messages',                       // MUST match server channel_key
  'Support',                                // user-visible name
  description: 'Messages from the AiHealth support team',
  importance: Importance.high,
  playSound: true,
);

await flutterLocalNotificationsPlugin
    .resolvePlatformSpecificImplementation<
        AndroidFlutterLocalNotificationsPlugin>()
    ?.createNotificationChannel(supportChannel);
```

iOS uses the same APNS payload as regular chat — no per-channel setup
needed.

When you receive an FCM message, the `data` map will contain:

```json
{
  "channelKey": "support_messages",
  "groupKey": "support_group"
}
```

Use that to route taps into the support thread screen (not the regular
chat screen).

---

## 2. Auth

No new token. Use the same JWT as every other v1 endpoint, sent as
`Authorization: Bearer <token>`.

The server reads the role from the token. Patients and care providers
can both open tickets; only admins (and care_providers with
`role == "support_staff"`) can answer them — but the agent surface is
served by a **separate web dashboard**, not the Flutter apps. Treat
`/v1/admin/support_tickets/*` as out of scope for both Flutter apps.

---

## 3. Requester endpoints (patient + care_provider apps)

All paths below are prefixed with the API base URL. All responses use
the standard envelope:

```json
{
  "status": "success",
  "version": "...",
  "message": "...",
  "data": <payload>
}
```

### 3.1 Open a ticket

```
POST /v1/support_tickets
Authorization: Bearer <jwt>
Content-Type: application/json
```

**Body:**

```json
{
  "scope": "product",                  // "product" | "facility"
  "subject": "Can't log in",           // optional, max 200 chars
  "initial_message": "I keep getting kicked out after the OTP screen.",
  "media": null,                       // optional; same shape as chat media
  "health_facility_id": null           // REQUIRED when scope == "facility"
}
```

**Scope decision (do this in the UI):**
- `product` — anything about the app itself (login, billing, bugs,
  account, feature questions). Routed to the AiHealth team.
- `facility` — questions for the patient's care facility (appointments,
  facility-specific policies, non-clinical help). Routed to the
  facility's support staff. Patient app should pass the patient's
  current `health_facility_id`; care provider app should pass the
  provider's facility id.

**Response 200:**

```json
{
  "status": "success",
  "message": "Support ticket opened.",
  "data": {
    "_id": "f4e2…",                 // ticket id
    "chat_id": "9b71…",             // chat id — use this for messaging
    "scope": "product",
    "requester_id": "<user_id>",
    "requester_type": "patient",    // or "care_provider"
    "health_facility_id": null,
    "subject": "Can't log in",
    "status": "open",
    "created_at": "2026-05-14T…",
    "updated_at": "2026-05-14T…",
    "last_message_at": "2026-05-14T…",
    "last_message_preview": "I keep getting kicked…",
    "resolved_at": null,
    "closed_at": null
  }
}
```

**Errors:**
- `400` — `scope: facility` without `health_facility_id`, or invalid UUID
- `400` — `initial_message` empty or > 4000 chars
- `401` — missing/expired token
- `422` — invalid `scope` value

After this succeeds you have a `chat_id` — that's the conversation. Use
the regular chat endpoints below to read/send messages on it.

### 3.2 List my tickets

```
GET /v1/support_tickets/mine
GET /v1/support_tickets/mine?status=open
GET /v1/support_tickets/mine?status=open&limit=20&offset=0
```

- `status` (optional): `open` | `pending` | `resolved` | `closed`
- `limit` (default 20, max 100)
- `offset` (default 0)

Returns an array of ticket docs (same shape as the open response).
Sorted by `last_message_at` desc — most recent activity first. Use this
to render the inbox.

### 3.3 Get one ticket

```
GET /v1/support_tickets/{ticket_id}
```

Returns the single ticket. `404` if it isn't theirs.

### 3.4 Close a ticket (requester self-close)

```
POST /v1/support_tickets/{ticket_id}/close
```

Returns the updated ticket with `status: "closed"` and `closed_at` set.
A subsequent agent reply will reopen it as `status: "pending"`.

---

## 4. Messaging inside a ticket — reuse existing chat APIs

There's **no new "send message in a ticket" endpoint**. Once you have a
`chat_id` from the ticket, use the same chat surface you already have:

### 4.1 Send a message

```
POST /chats/send_message
```

Body — identical to today:

```json
{
  "chat_id": "9b71…",
  "sender_id": "<your user_id>",      // MUST equal authenticated user
  "content": "screenshot attached",
  "media": { "type": "image", "url": "https://s3…", "caption": null },
  "reply_to": null,
  "timestamp": "2026-05-14T12:00:00Z",
  "metadata": { "type": "image", "status": "sent" }
}
```

> ⚠️ **Breaking change** (already on the branch): the server now rejects
> requests where `sender_id != authenticated_user_id` (HTTP 403) and
> rejects when the user is not a participant of `chat_id` (HTTP 403).
> If your current Flutter code ever sends a mismatched sender_id or
> calls send_message on a chat the user doesn't belong to, fix it now.

### 4.2 Fetch chat history

```
GET /chats/messages?chat_id=9b71…
```

Same as today. Returns the full message list sorted by timestamp asc.

### 4.3 Mark as read / reactions / edit

Same Socket.IO events as today: `markAsRead`, `toggleReaction`,
`editMessage`. They all work on support chats with no changes.

### 4.4 Attachments

Same flow:
1. `POST /file_upload/generate_presigned_url/` with `folder_path: "support/<chat_id>"` (any path you like)
2. `PUT` the file directly to the returned S3 URL
3. Include the S3 URL as `media.url` in the message body

---

## 5. Splitting "support" out of the normal chat list

`GET /chats` (the existing endpoint) now returns each chat's `kind`
field. Treat it as:

| `kind` value         | Meaning                          | UI placement              |
|----------------------|----------------------------------|---------------------------|
| `"direct"` or missing| Patient ↔ care provider 1-on-1   | Main "Chats" tab          |
| `"group"`            | Group chat (existing)            | Main "Chats" tab          |
| `"support"`          | Support ticket conversation      | Separate "Support" screen |

Legacy chats from before this release have no `kind` field — treat
missing as `"direct"`.

Two ways to render support threads:

**Option A — single source of truth:** keep using `GET /chats`, filter
client-side by `kind == "support"`, and use `GET /v1/support_tickets/mine`
only to fetch ticket *metadata* (status, subject) keyed by `chat_id`.

**Option B — dedicated inbox:** use `GET /v1/support_tickets/mine` for
the support inbox UI (sorted, paged, status-filterable out of the box),
and `GET /chats/messages?chat_id=…` when the user opens a thread.

Option B is cleaner if you want a real "Support" screen with status
badges, filters, etc. Either works.

---

## 6. Real-time updates (Socket.IO)

Connect to `/ws?authToken=<jwt>` exactly like you do today. **No new
events.** The existing ones cover support too:

| Event                          | When it fires                                |
|--------------------------------|----------------------------------------------|
| `new_message_received`         | Agent sends a reply, or you send one         |
| `message_updated`              | Edit or reaction toggle                      |
| `message_marked_as_read`       | Per-message read receipt                     |
| `all_messages_marked_as_read`  | "Mark all read" on a chat                    |
| `chat_list_updated`            | Ticket status changes (open → resolved etc.) — refresh both the chat list AND the support inbox |

Listen for `chat_list_updated` and refetch `GET /v1/support_tickets/mine`
so the inbox status badge updates without polling.

> ⚠️ **Breaking change** for Socket.IO clients: the server now rejects
> events where the payload's `sender_id`/`user_id` differs from the
> session-authenticated user, and rejects events on chats the user isn't
> a participant of. Reflects an `error` event with `status: "error"`.
> Make sure your client always sends the current user's id, never a
> cached value from another session.

---

## 7. Status lifecycle (v1)

```
        ┌──────────┐  agent replies        ┌──────────┐
        │   OPEN   │ ───────────────────►  │  PENDING │
        └──────────┘                       └──────────┘
             │                                   │
   resolve   │   resolve                         │ resolve
             ▼                                   ▼
        ┌──────────┐    requester or agent    ┌──────────┐
        │ RESOLVED │ ───────────────────────► │  CLOSED  │
        └──────────┘                          └──────────┘
             ▲                                     │
             └─────────── new reply ───────────────┘
                          (reopens as PENDING)
```

What this means for the UI:
- A fresh ticket is `open`. Show it prominently.
- Once an agent has replied at least once on an `open` or never-replied
  ticket, the server may flip it to `pending` (waiting on the
  requester). Render `pending` as "awaiting your response".
- Agents (or the requester, via `/close`) move tickets to `resolved` /
  `closed`. Both terminal states behave the same in v1.
- If anyone (agent or requester) sends a new message on a `resolved`
  or `closed` ticket, it reopens to `pending`. UI should not surprise
  the user — show the new status as soon as the next message comes in.

No assignment, categories, SLA, or canned replies in v1.

---

## 8. End-to-end scenarios

### 8.1 Patient opens a product-support ticket

1. User taps "Contact AiHealth" in the patient app.
2. App shows a form: optional subject, required message, optional
   attachment.
3. POST `/v1/support_tickets` with `scope: "product"`.
4. App stores `ticket_id` + `chat_id` from the response.
5. App navigates to a thread screen, fetches messages with
   `GET /chats/messages?chat_id=<chat_id>` — there will be exactly one
   message (the one just sent).
6. Socket.IO is already connected; further messages arrive via
   `new_message_received`.

### 8.2 Care provider opens a facility-support ticket

Same as 8.1 but `scope: "facility"` and pass the provider's
`health_facility_id` from their profile. The ticket will only be visible
to support_staff at that same facility.

### 8.3 Receiving an agent reply (background)

1. FCM arrives with `channelKey: "support_messages"`, `groupKey:
   "support_group"`, title `"Support Update"`, body = first ~200 chars
   of the message.
2. User taps the notification.
3. App reads `chat_id` from the notification payload's `data` map
   (you'll need to ensure the server includes `chat_id` — for now, the
   notification body identifies the support context; you can route to a
   generic "Support" screen and let the user pick the thread, or wire a
   small server change to embed `chat_id`. See "Optional follow-ups".)

### 8.4 Closing a thread

User taps "Close" on their ticket → `POST /v1/support_tickets/{id}/close`
→ inbox UI moves it to the "Closed" section. If support later replies,
the next `chat_list_updated` socket event signals the inbox to refresh
and the ticket reappears as `pending`.

---

## 9. Error handling reference

| Status | When                                                          |
|--------|---------------------------------------------------------------|
| 400    | Validation: missing `health_facility_id` for facility scope, malformed UUID, empty/oversized message |
| 401    | Missing/expired/invalid JWT                                   |
| 403    | `sender_id` mismatch, non-participant on a chat               |
| 404    | Ticket not found (or not yours)                               |
| 422    | Pydantic validation: invalid scope/status enum                |
| 500    | Server error — show generic "something went wrong"            |

The error body is the standard envelope:

```json
{
  "status": "error",
  "message": "human-readable message",
  "detail": "additional context, optional"
}
```

---

## 10. Optional server follow-ups (flag if you need them)

These weren't in the v1 backend scope but are easy to add if the apps
need them:

1. **Include `chat_id` and `ticket_id` in FCM `data` payload** —
   currently the support FCM only carries `channelKey` and `groupKey`.
   For deep-linking from a notification tap, you'll want the ids in
   `data` so the app can navigate straight to the right thread. Ask
   backend to add `data.chat_id` / `data.ticket_id` on the FCM payload
   for `kind == "support"` chats.
2. **Enrich `GET /chats/messages` with ticket metadata** — right now
   you have to call `/v1/support_tickets/{id}` separately to get the
   status. If the apps end up making both calls every time, the server
   can join them.
3. **Push status changes via a dedicated socket event** —
   `chat_list_updated` is fine but coarse. A typed `ticket_status_changed`
   event with the new status in the payload would let you update the
   inbox without a refetch.

None of these block v1. Ask if you hit friction.

---

## 11. Things NOT to build in v1

These are explicit v2 backlog items — don't waste time on them now,
they'll need backend changes too:

- Agent assignment / "claim this ticket" UI
- Category/tag picker on ticket open
- SLA countdown timers / breach indicators
- Canned-reply quick picks
- CSAT rating prompt after close

---

## 12. Quick start checklist

- [ ] Register `support_messages` Android channel in both apps
- [ ] Add "Contact Support" entry point (patient app + care provider app)
- [ ] Implement ticket open form → POST `/v1/support_tickets`
- [ ] Implement support inbox screen → GET `/v1/support_tickets/mine`
- [ ] Implement support thread screen — reuses existing chat thread UI
      with chat_id from the ticket
- [ ] Filter/split `GET /chats` results by `kind == "support"` (or hide
      support chats from the regular chat list entirely if you use a
      dedicated inbox)
- [ ] Refresh inbox on `chat_list_updated` Socket.IO event
- [ ] Audit existing `send_message` and Socket.IO calls — make sure
      `sender_id` always matches the authenticated user (the server now
      enforces this)

That's it. The whole thing is "chat plus a thin ticket header" — once
the entry point is wired, everything else falls out of the existing
chat infra.
