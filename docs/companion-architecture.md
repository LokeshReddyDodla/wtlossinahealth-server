# Companion Architecture — from Oracle to Companion

*Design doc, July 2026. Grounded in a 5-agent code study of both repos (server + Flutter app); every claim below was verified against source.*

## Problem

The health agent answers questions excellently but has no agency: it never asks,
never requests data, never follows up, and delivers essays instead of
conversation. Users experience question → answer, not a relationship.

## What the study found (the short version)

The companion already exists in fragments — never wired together:

| Fragment | Where it lives | State |
|---|---|---|
| Asking-back | `final_response_voice.md` (mandated!), WhatsApp prompt (encouraged) | App prompt **forbids** it (`system_patient.md` "Don't ask unnecessary questions") |
| Question memory | v2 `ThreadState.last_assistant_question` + `pending_slots` | **Dropped in the v3 rewrite**; v3 has transcript replay only (8 msgs) |
| Learning from answers | `FactExtractor` | **Structurally broken**: receives only the isolated user message, never the question it answers |
| Proactive→chat | `PROACTIVE_INSIGHT` EventBus publish (`monitor agent`) | **No subscriber** — dead wire, exactly where chat-injection belongs |
| Notification→chat | FCM payload has `suggested_query` | No route/thread_id/ref; app routes to insights **list**; inbox tap is a **no-op** |
| Multi-bubble | App `chat_message_list` renders consecutive bot bubbles (voice mode proves it) | SSE ingestion collapses each turn into one bubble; server has no segmentation |
| Write path | All save primitives + prescription **draft→confirm** + meal **preview→save** | Chat tools are 100% read-only; no confirm gate, no Actor context, no provenance |
| Feedback | `submitFeedback` + trace IDs fully plumbed in app | **No widget ever calls it** (promised to dietitians in the clinical briefing) |

## Design principles

1. **Answer first, always.** A question-back never replaces an answer (locked
   companion-tone rule). Curiosity is earned by usefulness.
2. **One question max, with a reason.** A follow-up is allowed only when it
   (a) fills a data gap that blocks better analysis, (b) disambiguates an
   observed pattern, or (c) advances the patient's stated goal. Otherwise: none.
3. **Safety mutes curiosity.** Active hypo/urgent contexts: first aid only.
4. **Asking implies remembering.** Every question the agent asks must be able
   to become a memory when answered — otherwise don't ask.
5. **One conversation across surfaces.** Push, chat, timeline, logging are
   entry points to the same thread, not separate products.
6. **Nothing writes without a tap.** Agent proposes; human confirms. Always.
7. **Every behavior ships with its overcorrection guard eval** (monitor lesson:
   the fix that isn't guarded becomes next month's bug).

## Phase 1 — Conversational voice (prompts + bubble protocol)

**Follow-up questions.** `system_patient.md` tone rule replaced with the
calibrated rule (above). `final_response.md` gains a "Being a companion"
section; voice keeps its mandate but gains the safety exclusion.

**Multi-bubble protocol.** The responder separates natural message breaks with
a sentinel line `[[BUBBLE]]` (between paragraphs only, never inside code
fences/tables, 1–4 bubbles per turn). Server-side handling — fully
backward-compatible:

- Streaming tokens pass through a stateful filter that removes sentinels
  mid-stream (old and new apps never see the literal).
- The final `done` payload / `QueryResponse` carries **both** `full_response`
  (sentinels → paragraph breaks; unchanged rendering for current apps) and
  `data.messages: list[str]` (the split bubbles; new apps render as separate
  bubbles at finalize).
- WhatsApp: the router splits server-side and sends 1–4 actual WhatsApp
  messages — multi-bubble is live there with zero app work.
- Voice: sentinel banned (one short spoken answer).

**App-team contract (Phase 1):** render `done.data.messages[]` as separate
bubbles when present (fallback: `full_response`). List already supports it.

## Phase 2 — Asking means learning (the flywheel)

- `FactExtractor.extract_if_needed` gains `preceding_assistant_message` so
  "yes, around 1am" becomes `{sleep_pattern: "slept ~1am on <date>"}` instead
  of evaporating.
- V3-native thread micro-state (Mongo, on/next to `ThreadSummary`):
  `last_assistant_question`, `pending_data_request {entity_type, ttl, asked_at}`.
  Written by the persistence service at save-turn; read by context loader.
- Populate the dead `ThreadSummary.goal/domains/date_scope` fields at
  compaction (schema already exists).
- Evals: answer→fact capture; follow-up resolution beyond the 8-message window;
  guard: unanswered questions are dropped, never re-asked verbatim.

## Phase 3 — One conversation across surfaces (the closed loop)

Target scene: agent asks "log your lunch and I'll take a look" → patient logs →
analysis appears **in the chat** + push opens **that conversation**.

Pieces (all named, all verified missing):
1. **Pending-request record** keyed by thread: expected trigger/entity type +
   TTL, written when the agent asks for data.
2. **Correlation** through the event path: `handle_proactive_event` checks
   pending requests for the patient; on match, the event-scan insight becomes a
   *conversation continuation*.
3. **Chat injection**: subscriber on the currently-dead `PROACTIVE_INSIGHT`
   EventBus wire appends an assistant turn to `bot:patient:{id}`.
4. **FCM payload extension**: `route:"chat"`, `thread_id`, `insight_id`-as-ref;
   app routes proactive insights to chat with auto-attached
   `refs:[{type:"insight",id}]` (also fixes: inbox no-op; insights-list detour).
5. **Chat→logging chips**: agent can emit action chips (`log_meal`, `log_smbg`)
   that open the existing sheets (already invocable from the notification
   controller — no new sheet infra).

## Phase 4 — Hands, with consent (agent writes; only on explicit go)

"Want me to log that?" — propose→confirm, modeled on the prescription
draft→confirm (server-held) and the meal preview→save (client-held) patterns.

Must-build list (verified absent): write tool(s) with data services injected
into `ToolExecutor`; confirm gate (ghost card in chat; nothing persists without
a tap); **Actor-grade auth inside the tool executor** — agent writes only to
the authenticated patient's own id, never a provider-panel patient; `agent`
provenance value on `source` fields for audit; idempotency key against
double-proposes. First candidate: meal-from-chat-text (the preview pipeline
already turns text into a full ghost meal today).

## Case matrix (each becomes an eval or an explicit non-goal)

| # | Scenario | Required behavior |
|---|---|---|
| 1 | Pattern found, adjacent data missing | Answer + ONE follow-up tied to the gap |
| 2 | Simple factual lookup ("avg glucose yesterday?") | Direct answer; no interrogation |
| 3 | Patient answers the follow-up ("yes, ~1am") | Becomes a durable fact (Phase 2) |
| 4 | Patient ignores the question, changes topic | Drop it; never re-ask verbatim |
| 5 | Terse close ("ok thanks") | Short warm close, no new question |
| 6 | Active hypo / urgent | First aid only; zero curiosity |
| 7 | Med-dose question | Care-team redirect; no follow-up question that implies dosing advice |
| 8 | Weight-loss persona | Curiosity in THEIR frame (satiety/energy), zero glucose talk |
| 9 | Provider panel query | No companion chattiness; professional register; never "my/your" |
| 10 | Greeting/small talk | Warmth, no data dump, at most one light opener |
| 11 | Repeated daily question | Vary phrasing; reference continuity ("still trending better than last week") |
| 12 | "Log that for me" (pre-Phase-4) | Graceful: explain + one-tap path to the right sheet; never pretend it logged |
| 13 | Multi-domain overview | 2–4 bubbles, each self-contained, story order |
| 14 | Voice turn | One short answer + spoken follow-up; no sentinel |
| 15 | WhatsApp turn | Real multiple messages; WhatsApp markdown only |
| 16 | Data-ask when data already exists | Never ask for what's already logged |
| 17 | Question budget | ≤1/turn; if last turn's question went unanswered, none this turn |
| 18 | Notification tap (Phase 3) | Lands in chat, insight ref attached, context loaded |
| 19 | Logged-after-ask (Phase 3) | Analysis continues the SAME thread |
| 20 | Ghost-card confirm (Phase 4) | Nothing persists without explicit tap; provenance recorded |

## Sequencing & verification

Phase 1 now (prompts, bubbles, WhatsApp split, companion eval suite) →
Phase 2 (fact-extractor context + thread micro-state) → Phase 3 (closed loop,
needs app-team routing work) → Phase 4 (on explicit go).

Every phase: unit tests + golden eval gate (companion cases added per phase,
each with its overcorrection guard) + 3× consistency runs before merge.
Independent quick fixes queued with the app team: inbox no-op, feedback UI
wiring (promised to dietitians), dropped SSE reasoning events.
