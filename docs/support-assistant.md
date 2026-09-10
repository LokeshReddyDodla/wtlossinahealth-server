# Patient Support Assistant

AI first responder inside patient support tickets. It answers what the knowledge base
covers, and turns everything else into a clean hand-off so the patient knows the team
will reply in the same chat.

## Where it runs

Every message saved to a chat of kind `support` passes through
`ChatMessagingService.add_message`. That branch calls
`lib/services/support/support_assistant_service.py::schedule_reply`, which runs the
assistant off the request path (fire-and-forget, strong task refs). The bot replies only
while all of these hold:

| Condition | Why |
|---|---|
| Ticket was opened by a **patient** | Care-provider tickets are staff-to-staff |
| Sender is the ticket's requester | Never answers itself or a staff reply |
| **No human agent is a chat participant** | Agents join on their first reply; from then on the bot is silent for that ticket |
| Feature `support_assistant` is enabled for the patient's facility | Admin → AI features toggle, system or facility scope |
| Fewer than `AI_SUPPORT_ASSISTANT_MAX_REPLIES_PER_TICKET` bot replies so far | Never loops with a frustrated patient |

The bot never changes ticket status and never writes patient data.

## What one turn does

1. Builds a read-only **patient snapshot** (`SupportAssistantSnapshotService`): care
   team names/roles/phones/emails, facility phone and emergency phone, active package,
   the five app permissions as last reported, LibreView/Sinocare sync state, last meal
   date and 7-day count, last five documents on record, phone platform and app version.
   Each section fails independently and is labelled "could not be checked" in the prompt.
2. Loads the last `AI_SUPPORT_ASSISTANT_HISTORY_MESSAGES` messages of the ticket.
3. One structured LLM call (`ModelTask.SUPPORT_ASSISTANT`, route in
   `models/registry.py`) returns a `SupportTriage`: category, urgency, `needs_human`,
   one-line English summary for staff, and the reply in the patient's language.
4. **Policy in code** (`SupportAssistantAgent._decide_mode`) decides what is sent:

| Mode | When | Patient sees |
|---|---|---|
| `answered` | self-serve category and `needs_human` false | the model's reply |
| `held_for_human` | any non-self-serve category, or `needs_human` true, or empty reply | model's short ack + standard hold message |
| `redirected_medical` | category `medical_question` | model's one-liner + care-team contact block |
| `emergency` | category `emergency` | emergency template (108/112, facility emergency phone, care team), model reply discarded |

   If the LLM call fails entirely, the patient still gets an honest hold message and the
   ticket is marked `needs_human`.
5. Posts the reply through the normal chat path as sender
   `SUPPORT_ASSISTANT_SENDER_ID`, which resolves to the profile "Support Assistant" with
   role `admin` so current app builds render it on the support side with no change.
6. `$set`s `assistant.*` on the ticket document (category, urgency, needs_human, summary,
   handling_mode, reply_count, last_replied_at, last_trace_id), targeted by `_id`.

## Editing what it knows

The brain is two files, no code change needed:

- `lib/ai_foundation/agents/support_assistant/knowledge/system_prompt.md` — behaviour
  and boundaries.
- `lib/ai_foundation/agents/support_assistant/knowledge/knowledge_base.md` — the app
  reference: screens, flows, timings, what to hold for a person.

They load once at startup; restart to pick up edits. Keep screen and button names in
**bold** only when they are real labels in the app. The hold, medical-redirect and
emergency texts are constants in `agent.py` and go through `TranslationService`.

## Staff queue

`GET /v1/admin/support_tickets` accepts `needs_human=true|false`. Every ticket the bot
touched carries the `assistant` sub-document, so the dashboard can show the category,
urgency and summary next to the patient's message.

## Tunables (`AI_*` env, see `lib/ai_foundation/config.py`)

`SUPPORT_ASSISTANT_MAX_REPLIES_PER_TICKET` (6), `SUPPORT_ASSISTANT_HISTORY_MESSAGES`
(12), `SUPPORT_ASSISTANT_TIMEOUT_SECONDS` (45), `SUPPORT_ASSISTANT_TEMPERATURE` (0.2).

## App-team note

Nothing is required for the first version. Optional later: show an "automated reply"
label on messages whose `sender_profile` is `Support Assistant`.
