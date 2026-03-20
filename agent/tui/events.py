from __future__ import annotations

from asyncio import Queue
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any


class EventKind(Enum):
    THINKING = auto()
    PLAN_READY = auto()
    STEP_START = auto()
    STEP_SUCCESS = auto()
    STEP_FAILURE = auto()
    RETRY = auto()
    SNAPSHOT = auto()
    REPLY = auto()
    TODO_UPDATE = auto()
    AWAITING_APPROVAL = auto()
    TOKEN_STREAM = auto()


@dataclass(slots=True)
class AgentEvent:
    kind: EventKind
    message: str
    detail: dict[str, Any] = field(default_factory=dict)


class EventBus:
    def __init__(self) -> None:
        self._queue: Queue[AgentEvent] = Queue()

    async def publish(self, event: AgentEvent) -> None:
        await self._queue.put(event)

    async def next(self) -> AgentEvent:
        return await self._queue.get()
