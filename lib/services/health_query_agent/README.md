# Health Query Agent

## Package structure

This package now uses a single production architecture.

### Root package
The root package contains only service shell and infrastructure pieces:

- `service.py`
- `workflow.py`
- `conversation_repository.py`
- `checkpointer.py`
- `state_constants.py`
- `serialization.py`
- `prompts/`

### `v2/`
The `v2/` package contains the actual runtime logic and contracts:

- `contracts.py`: intent, response, state, and enum contracts
- `conversation_resolver.py`: follow-up and context resolution
- `planner.py`: intent planning and retrieval planning
- `tool_executor.py`: execution of the selected tool chain
- `analysis.py`: structured analysis from retrieved payloads
- `response_formatter.py`: deterministic response scaffolds
- `response_writer.py`: final response prompt assembly
- `memory_repository.py`: patient memory, thread state, snapshots, compactions
- `compaction.py`: conversation compaction builder
- `playbook_loader.py` and `playbooks/`: domain playbooks
- `prompt_builder.py`: prompt asset assembly
- `filter_builder.py` and `qdrant_search.py`: Qdrant retrieval internals

## Runtime flow

`resolver -> planner -> tool executor -> analyzer -> formatter -> writer -> memory persistence`

## Rules

- New health-agent runtime logic should go into `v2/`.
- Root-level files should only be used for package shell and infrastructure.
- Do not reintroduce duplicate root-level contract or retrieval modules.
