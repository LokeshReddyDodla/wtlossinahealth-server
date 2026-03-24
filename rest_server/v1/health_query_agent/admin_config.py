"""
Admin Config Endpoint — view and update model configuration at runtime.

No code changes needed to switch models or add new providers. Just call
these endpoints.
"""

from typing import Any

from fastapi import Depends
from pydantic import BaseModel, Field

from lib.core.constants import ProfileTypeEnum
from lib.core.container import container
from lib.dependencies.actor import Actor, get_current_actor
from lib.ai_foundation.models.registry import ModelRegistry, ModelSpec, ModelTask, ModelProvider, TaskRoute
from rest_server.response_models import SuccessResponse

from .router import router


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class ModelConfigResponse(BaseModel):
    models: list[dict[str, Any]]
    routes: dict[str, dict[str, Any]]


class UpdateRouteRequest(BaseModel):
    task: str = Field(..., description="Task name: intent_extraction, response_generation, etc.")
    primary: str = Field(..., description="Primary model_id")
    fallbacks: list[str] = Field(default_factory=list, description="Fallback model_ids in order")


class RegisterModelRequest(BaseModel):
    model_config_data: dict[str, Any] = Field(..., alias="model", description="ModelSpec fields")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/admin/config", response_model=SuccessResponse[ModelConfigResponse])
async def get_model_config(
    current_actor: Actor = Depends(
        get_current_actor(
            allowed_roles=[ProfileTypeEnum.ADMIN],
            check_permissions=False,
        )
    ),
):
    """View all registered models and task routes. Admin only."""
    registry: ModelRegistry = container.resolve(ModelRegistry)

    models = [
        {
            "model_id": m.model_id,
            "provider": m.provider.value,
            "temperature": m.temperature,
            "timeout_seconds": m.timeout_seconds,
            "cost_per_1k_input": m.cost_per_1k_input,
            "cost_per_1k_output": m.cost_per_1k_output,
            "supports_streaming": m.supports_streaming,
            "supports_structured": m.supports_structured,
            "tags": m.tags,
        }
        for m in registry.list_models()
    ]

    routes = {}
    for task, route in registry.list_tasks().items():
        routes[task.value] = {
            "primary": route.primary,
            "fallbacks": route.fallbacks,
        }

    return SuccessResponse(
        message="Model configuration retrieved",
        data=ModelConfigResponse(models=models, routes=routes),
    )


@router.post("/admin/config/route", response_model=SuccessResponse[dict])
async def update_task_route(
    payload: UpdateRouteRequest,
    current_actor: Actor = Depends(
        get_current_actor(
            allowed_roles=[ProfileTypeEnum.ADMIN],
            check_permissions=False,
        )
    ),
):
    """Update which model handles a task. Takes effect immediately. Admin only.

    Example: switch response generation from gpt-5.1 to gemini-2.5-pro:
    {"task": "response_generation", "primary": "gemini-2.5-pro", "fallbacks": ["gpt-5.1"]}
    """
    registry: ModelRegistry = container.resolve(ModelRegistry)

    try:
        task = ModelTask(payload.task)
    except ValueError:
        valid = [t.value for t in ModelTask]
        return SuccessResponse(message=f"Invalid task. Valid: {valid}", data={"error": True})

    try:
        registry.set_task_route(task, primary=payload.primary, fallbacks=payload.fallbacks)
    except Exception as e:
        return SuccessResponse(message=str(e), data={"error": True})

    return SuccessResponse(
        message=f"Route updated: {payload.task} → {payload.primary} (fallbacks: {payload.fallbacks})",
        data={"task": payload.task, "primary": payload.primary, "fallbacks": payload.fallbacks},
    )


@router.post("/admin/config/model", response_model=SuccessResponse[dict])
async def register_model(
    payload: RegisterModelRequest,
    current_actor: Actor = Depends(
        get_current_actor(
            allowed_roles=[ProfileTypeEnum.ADMIN],
            check_permissions=False,
        )
    ),
):
    """Register a new model or update an existing one. Admin only.

    Example: add a fine-tuned model:
    {"model": {"model_id": "ft:gpt-4.1-mini:health-v1", "provider": "openai", "temperature": 0.0}}
    """
    registry: ModelRegistry = container.resolve(ModelRegistry)

    try:
        data = payload.model_config_data
        if "provider" in data:
            data["provider"] = ModelProvider(data["provider"])
        spec = ModelSpec(**data)
        registry.register(spec)
    except Exception as e:
        return SuccessResponse(message=str(e), data={"error": True})

    return SuccessResponse(
        message=f"Model registered: {spec.model_id} ({spec.provider.value})",
        data={"model_id": spec.model_id, "provider": spec.provider.value},
    )
