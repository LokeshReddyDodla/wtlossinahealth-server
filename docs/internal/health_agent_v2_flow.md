# Health Agent V2 Flow

## Purpose
This document explains the single production request path for the health agent. It focuses on:
- request flow
- decision points
- storage interactions
- memory write path

There is one runtime architecture only:

`resolver -> planner -> tool executor -> analyzer -> formatter -> writer -> memory persistence`

## Request Path

```text
User Message
  |
  v
HealthQueryAgentService.process_message
  |
  |-- load recent thread messages from LangGraph/Redis
  |-- load patient memory from Mongo
  |-- load thread fallback state from Mongo
  |-- save raw user message to Mongo conversation history
  |
  v
ConversationResolver
  |
  |-- classify message:
  |     fresh_query / follow_up / clarification_answer / goal_update / conversational
  |
  |-- extract explicit facts:
  |     goal / fasting / weight / training_timing / communication_style
  |
  |-- inherit context:
  |     domains / goal / date_scope / pending_slots
  |
  v
Workflow.ainvoke
  |
  v
Intent Extraction LLM (gpt-4.1-mini)
  |
  |-- input:
  |     bounded recent turns
  |     runtime conversation context
  |     durable patient memory facts
  |
  v
QueryIntent
  |
  v
V2Planner
  |
  |-- build IntentPlan
  |     domains
  |     response_mode
  |     requested_goal
  |     date_scope
  |     has_temporal_scope
  |
  |-- build RetrievalPlan
  |     tool_chain
  |     result_limit
  |     use_qdrant?
  |     use_patient_summary?
  |     enrichments
  |     playbooks
  |
  v
ToolExecutor
  |
  |-- if exact temporal list/summarize/compare:
  |     mongo_report_fetch
  |
  |-- if semantic/evaluative:
  |     qdrant_search
  |
  |-- if broad overview / sleep / vitals / cross-domain:
  |     patient_summary_fetch
  |
  v
Normalized Payloads
  |
  v
StructuredAnalyzer
  |
  |-- build AnalysisSnapshot
  |     meals / cgm / fitness / sleep / vitals / docs / patient_summary
  |     highlights
  |     evidence
  |
  v
ResponseFormatter
  |
  |-- build deterministic scaffold by mode:
  |     list / summarize / evaluate / compare / recommend / clarify
  |
  v
ResponseWriterSupport
  |
  |-- assemble final prompt package:
  |     structured analysis
  |     playbooks
  |     response-mode contract
  |     retrieval-source contract
  |     formatter scaffold
  |
  v
Final Response LLM (gpt-5.1)
  |
  v
Assistant Message
```

## Memory Write Path

```text
Assistant Message Produced
  |
  v
HealthQueryAgentService
  |
  |-- save assistant message to Mongo conversation history
  |     includes:
  |       intent
  |       response
  |       retrieval metadata
  |
  |-- append assistant turn to LangGraph/Redis thread state
  |
  |-- persist explicit user facts to Mongo patient memory
  |     examples:
  |       goal=fat_loss
  |       fasting=ramadan
  |       weight_kg=71.35
  |
  |-- persist thread state to Mongo
  |     active_domains
  |     active_goal
  |     active_date_scope
  |     pending_slots
  |     last_assistant_question
  |     last_assistant_response
  |
  |-- persist analysis snapshot to Mongo
  |
  |-- enqueue async conversation compaction periodically
  |
  v
Ready for next turn
```

## Storage Interaction Map

```text
Redis / LangGraph
  - short-term thread turns
  - active session continuity

Mongo
  - health_query_conversations
  - patient_agent_memory
  - thread_agent_state
  - analysis_snapshots
  - conversation_compactions
  - patient_summaries
  - raw report collections

Qdrant
  - semantic retrieval only
  - meal / cgm / smbg / fitness / profile / docs vectors

Final LLM path
  - never reads raw DBs directly
  - reads structured analysis prepared by the app
```

## Decision Tree

```text
New user message
  |
  |-- follow-up resolvable from context?
  |      yes -> inherit domain/goal/date scope
  |      no  -> rely on fresh intent extraction
  |
  |-- intent ready?
  |      yes -> build execution plan
  |      no  -> can summary-only path execute?
  |                yes -> continue
  |                no  -> clarify
  |
  |-- temporal + report-backed + list/summarize/compare?
  |      yes -> exact Mongo report fetch
  |      no  -> consider Qdrant
  |
  |-- evaluation / semantic query?
  |      yes -> Qdrant
  |
  |-- broad overview / sleep / vitals / cross-domain?
  |      yes -> patient_summary_fetch
  |
  v
Analyze -> format scaffold -> final response

If no payloads are found for an exact query:
  -> return deterministic no-data response

If final LLM generation times out or fails:
  -> return deterministic formatter-based fallback response
```

## Simple Mental Model

```text
Resolver decides what the message means.
Planner decides what data path to use.
Tools fetch the data.
Analyzer turns raw data into signal.
Formatter decides answer shape.
LLM writes the final natural-language response.
Service persists memory for the next turn.
```

## Design Split

```text
Control Plane
  - conversation resolver
  - planner
  - memory

Execution Plane
  - mongo_report_fetch
  - qdrant_search
  - patient_summary_fetch

Presentation Plane
  - analyzer
  - formatter
  - response writer
  - final LLM
```

## Current Routing Rules
- Use exact Mongo report fetch for temporal `list`, `summarize`, and `compare` queries on report-backed domains:
  - `meal`
  - `cgm`
  - `fitness`
  - `sleep`
- Use Qdrant only for semantic or evaluative requests where exact report fetch is not the right primary path.
- Use patient summary fetch for overview, sleep/vitals support, and mixed-domain summary enrichment.
- Conversation lexicon is config-backed, not hardcoded inline in the resolver.
- Use Qdrant primarily for semantic and evaluative queries.
- Use patient summaries for overview, sleep/vitals support, and some mixed-domain cases.
- Persist assistant turns back into thread state after every response.
- Persist durable patient facts only when they are explicit or high-confidence.

## Open Work
- Add async compaction worker for `conversation_compactions`
- Add broader exact-fetch support for more mixed-domain compare cases if needed
- Add ranking/filter layer before formatting to reduce noise when payload counts are large
