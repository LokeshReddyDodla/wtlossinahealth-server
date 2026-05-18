# Testing the Support Tickets feature

A bare-bones HTML dashboard for testing the **agent side** of the
support ticket flow without building a full admin UI. Pair it with the
Flutter apps (or the `curl` commands below) for the requester side and
you've got the whole loop.

## What's here

- `support-test-dashboard.html` — single-file agent dashboard. Open in a
  browser, paste JWT, answer tickets.
- This README — usage + manual curl fallbacks.

---

## 1. Set up two accounts

You need:

1. **A requester** — a `patient` or `care_provider` JWT. You probably
   already use these for normal Flutter app testing.
2. **An agent** — one of:
   - For `scope=product` tickets: an **Admin** account (`POST /v1/auth/admin/login` or however your admin auth flow goes).
   - For `scope=facility` tickets: a `CareProvider` whose `role` is
     `support_staff` and who has a `health_facility_id` set. The
     requester (if also a CareProvider or Patient) must belong to the
     same facility.

Without a valid agent JWT the dashboard will 403 on the queue endpoint.

---

## 2. Open the dashboard

```bash
# from repo root
open tools/support-test-dashboard.html       # macOS
xdg-open tools/support-test-dashboard.html   # Linux
```

Or just double-click it. It runs from `file://` — no server needed.

> **If you get CORS errors**: the API probably doesn't allow
> `file://null` as an origin. Two fixes:
>
> 1. Serve the file locally:
>    ```bash
>    cd tools && python3 -m http.server 8765
>    # then open http://localhost:8765/support-test-dashboard.html
>    ```
>    and add `http://localhost:8765` to the API's CORS allowed origins.
> 2. Or, if your API is on `localhost`, just host the HTML on the same
>    origin (e.g. drop it inside the FastAPI static dir temporarily).

---

## 3. Run the loop

1. **Open ticket from Flutter** (patient or care_provider app)
   - Pick scope (product vs facility)
   - Send the initial message
   - App should land on the ticket thread screen

2. **See it in the dashboard**
   - Paste your API base URL (e.g. `https://api-staging.aihealth.in`)
   - Paste your **agent** JWT
   - Click Connect
   - The new ticket appears in the left queue with a status pill
   - Queue auto-refreshes every 10s

3. **Open the ticket and reply**
   - Click the ticket row
   - You'll see the message thread on the right
   - Type a reply in the composer and hit Send (or ⌘/Ctrl + Enter)
   - First reply auto-adds you as a chat participant
   - Reply auto-flips status `open` → `pending` is *not* automatic; you
     stay on `open` until you explicitly change it (see step 5).
     Closed/resolved tickets DO auto-reopen to `pending` on reply.

4. **Watch it land in Flutter**
   - The patient/CP app should get a `new_message_received` Socket.IO
     event and update the thread live
   - It should also get an FCM with `channel_key: "support_messages"` if
     the app is backgrounded

5. **Change status**
   - Use the "Set …" dropdown in the ticket header
   - The status pill updates in the queue
   - The patient/CP app gets `chat_list_updated` and the inbox should
     refresh — they see the new status

6. **Requester closes from their side**
   - In the Flutter app, hit the "Close" action — calls
     `POST /v1/support_tickets/{id}/close`
   - Status flips to `closed` in the dashboard queue

---

## 4. Curl fallbacks (no Flutter needed)

If you want to test without the apps, drive the requester side from a
terminal. Replace `$BASE`, `$PATIENT_JWT`, `$AGENT_JWT` with your values.

### Open a product-scope ticket as a patient

```bash
curl -s -X POST "$BASE/v1/support_tickets" \
  -H "Authorization: Bearer $PATIENT_JWT" \
  -H "Content-Type: application/json" \
  -d '{
    "scope": "product",
    "subject": "Test ticket",
    "initial_message": "Hello from curl"
  }' | jq
```

Save the `data.chat_id` and `data._id` for next steps.

### Open a facility-scope ticket

```bash
curl -s -X POST "$BASE/v1/support_tickets" \
  -H "Authorization: Bearer $PATIENT_JWT" \
  -H "Content-Type: application/json" \
  -d '{
    "scope": "facility",
    "initial_message": "Facility help test",
    "health_facility_id": "<UUID of facility>"
  }' | jq
```

### Patient sends a follow-up

```bash
curl -s -X POST "$BASE/chats/send_message" \
  -H "Authorization: Bearer $PATIENT_JWT" \
  -H "Content-Type: application/json" \
  -d '{
    "chat_id": "<chat_id from open>",
    "sender_id": "<patient user_id>",
    "content": "another message",
    "timestamp": "'"$(date -u +%FT%TZ)"'",
    "metadata": { "type": "text", "status": "sent" }
  }' | jq
```

(Note: `sender_id` MUST equal the authenticated user — server enforces
this now. 403 otherwise.)

### Patient lists their tickets

```bash
curl -s "$BASE/v1/support_tickets/mine?limit=20" \
  -H "Authorization: Bearer $PATIENT_JWT" | jq
```

### Patient closes their ticket

```bash
curl -s -X POST "$BASE/v1/support_tickets/<ticket_id>/close" \
  -H "Authorization: Bearer $PATIENT_JWT" | jq
```

### Agent inspects the queue

```bash
curl -s "$BASE/v1/admin/support_tickets?limit=20" \
  -H "Authorization: Bearer $AGENT_JWT" | jq
```

Filters: `?scope=product`, `?status=open`, `?requester_type=patient` (combinable).

### Agent replies

```bash
curl -s -X POST "$BASE/v1/admin/support_tickets/<ticket_id>/reply" \
  -H "Authorization: Bearer $AGENT_JWT" \
  -H "Content-Type: application/json" \
  -d '{ "content": "we are looking into it" }' | jq
```

### Agent changes status

```bash
curl -s -X PATCH "$BASE/v1/admin/support_tickets/<ticket_id>/status" \
  -H "Authorization: Bearer $AGENT_JWT" \
  -H "Content-Type: application/json" \
  -d '{ "status": "resolved" }' | jq
```

---

## 5. Test matrix worth running once

Quick smoke checks that exercise the boundaries:

| # | Action | Expected |
|---|--------|----------|
| 1 | Patient opens product ticket | `status=open`, lands in admin queue, NOT in any facility staff queue |
| 2 | Patient opens facility ticket without `health_facility_id` | 400 from server |
| 3 | Patient opens facility ticket with facility A | Visible only to support_staff at facility A — try with support_staff at facility B → 404 |
| 4 | Patient B tries to GET patient A's ticket | 404 (don't leak existence) |
| 5 | Admin tries to access a facility ticket | 404 |
| 6 | Agent replies for first time | Agent appears as chat participant in `GET /chats/messages` thread |
| 7 | Agent sets resolved → patient replies | Status flips back to `pending` automatically |
| 8 | Agent sets resolved twice | `resolved_at` doesn't change on the second call (audit history preserved) |
| 9 | Patient sends `send_message` with someone else's `sender_id` | 403 |
| 10 | Patient sends `send_message` on a chat they don't belong to | 403 |
| 11 | Socket.IO `sendMessage` with mismatched `sender_id` | `error` event back, no message saved |
| 12 | FCM lands on patient's phone | Android channel = `support_messages`, group = `support_group` |

If all 12 behave as listed, the backend's good.

---

## 6. Notes / gotchas

- The dashboard uses **polling** (10s), not Socket.IO — keeps it simple
  and works through any proxy. If you want live updates, the existing
  Socket.IO events all fire correctly; you can wire them in later.
- JWT and API base URL are stored in `localStorage` — they survive page
  reloads. To switch accounts, paste a new JWT and click Connect.
- "Set status" only flips status; it doesn't send a message. Combine
  reply + status change manually if you want both.
- For `scope=facility` tests, make sure the `health_facility_id` you pass
  matches the support_staff CareProvider's facility — otherwise the
  ticket shows up in nobody's queue.
