from __future__ import annotations

import orjson
from dataclasses import dataclass, asdict, field
from datetime import datetime
from typing import Any, Optional
from uuid import uuid5, NAMESPACE_DNS

from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    Checkpoint,
    CheckpointTuple,
    CheckpointMetadata,
)

from lib.core.cache_store import CacheStore
from microservices.health_query_agent.config import settings
from .serialization import to_checkpoint_safe

# ------------------------------------------------------------------ #
# Model
# ------------------------------------------------------------------ #


@dataclass
class RedisCheckpoint:
    v: int = 1
    id: str = ""
    ts: str = ""
    channel_values: dict[str, Any] = field(default_factory=dict)
    channel_versions: dict[str, Any] = field(default_factory=dict)
    versions_seen: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(cls, thread_id: str) -> "RedisCheckpoint":
        return cls(
            id=RedisCheckpointSaver.thread_uuid(thread_id),
            ts=datetime.utcnow().isoformat(),
        )

    @classmethod
    def from_checkpoint(cls, checkpoint: dict) -> "RedisCheckpoint":
        allowed = {
            "v",
            "id",
            "ts",
            "channel_values",
            "channel_versions",
            "versions_seen",
        }
        return cls(**{k: v for k, v in checkpoint.items() if k in allowed})


# ------------------------------------------------------------------ #
# Redis Checkpoint Saver
# ------------------------------------------------------------------ #


class RedisCheckpointSaver(BaseCheckpointSaver):
    def __init__(self, cache_store: Optional[CacheStore] = None):
        if not cache_store:
            raise ValueError("Cache store not configured")

        self.cache_store = cache_store

        self.ttl = settings.CONVERSATION_STATE_TTL_HOURS * 3600

    # ------------------------ utils ------------------------ #

    @staticmethod
    def thread_uuid(thread_id: str) -> str:
        return str(uuid5(NAMESPACE_DNS, f"health-query-agent:{thread_id}"))

    def _key(self, thread_id: str) -> str:
        return thread_id

    def _thread_id(self, config: dict) -> Optional[str]:
        return config.get("configurable", {}).get("thread_id")

    # --------------------- serialization -------------------- #

    def _dump(self, checkpoint: RedisCheckpoint) -> bytes:
        cleaned = to_checkpoint_safe(asdict(checkpoint))
        return orjson.dumps(cleaned)

    def _load(self, data: bytes) -> RedisCheckpoint:
        return RedisCheckpoint.from_checkpoint(orjson.loads(data))

    # ----------------------- redis ops ---------------------- #

    def _save(self, thread_id: str, checkpoint: RedisCheckpoint) -> None:
        checkpoint_bytes = self._dump(checkpoint)
        checkpoint_str = checkpoint_bytes.decode('utf-8')
        self.cache_store.set_key(
            self._key(thread_id),
            checkpoint_str,
            expire=self.ttl,
        )

    def _fetch(self, thread_id: str) -> Optional[RedisCheckpoint]:
        data = self.cache_store.get_key(self._key(thread_id))
        if data is None:
            return None
            
        return self._load(data)

    # -------------------- LangGraph API --------------------- #

    async def put(
        self,
        config: dict,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: Optional[dict] = None,
    ) -> Optional[CheckpointTuple]:
        thread_id = self._thread_id(config)
        if not thread_id:
            return None

        cp = (
            RedisCheckpoint.from_checkpoint(checkpoint)
            if isinstance(checkpoint, dict)
            else RedisCheckpoint.create(thread_id)
        )

        if not cp.id:
            cp.id = self.thread_uuid(thread_id)

        cp.ts = cp.ts or datetime.utcnow().isoformat()

        self._save(thread_id, cp)

        return CheckpointTuple(config, checkpoint, metadata)

    async def aput(self, *args, **kwargs):
        return await self.put(*args, **kwargs)

    async def aput_writes(
        self,
        config: dict,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: Optional[dict] = None,
    ):
        return await self.put(config, checkpoint, metadata, new_versions)

    async def put_writes(
        self,
        config: dict,
        writes: dict,
        metadata: CheckpointMetadata,
    ) -> Optional[CheckpointTuple]:
        thread_id = self._thread_id(config)
        if not thread_id:
            return None

        cp = self._fetch(thread_id) or RedisCheckpoint.create(thread_id)
        cp.channel_values.update({k: to_checkpoint_safe(v) for k, v in writes.items()})
        cp.ts = datetime.utcnow().isoformat()

        self._save(thread_id, cp)

        return CheckpointTuple(config, asdict(cp), metadata)

    def get(self, config: dict) -> Optional[CheckpointTuple]:
        thread_id = self._thread_id(config)
        if not thread_id:
            return None

        cp = self._fetch(thread_id)
        if not cp:
            return None

        metadata = CheckpointMetadata(
            source="redis",
            step=-1,
            writes={},
            parents=[],
        )

        return CheckpointTuple(config, asdict(cp), metadata)

    def get_tuple(self, config: dict) -> Optional[CheckpointTuple]:
        return self.get(config)

    async def aget_tuple(self, config: dict):
        return self.get(config)

    async def list(self, *args, **kwargs):
        return []

    async def delete(self, config: dict) -> None:
        thread_id = self._thread_id(config)
        if thread_id:
            self.cache_store.delete_key(self._key(thread_id))
