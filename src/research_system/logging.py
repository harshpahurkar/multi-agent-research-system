from __future__ import annotations

from typing import Any

from .models import RunEvent


class RunLogger:
    def __init__(self) -> None:
        self.events: list[RunEvent] = []

    def add(self, node: str, event: str, **payload: Any) -> None:
        self.events.append(RunEvent(node=node, event=event, payload=payload))

    def to_state(self) -> list[dict[str, Any]]:
        return [event.model_dump(mode="json") for event in self.events]


def append_event(state_events: list[dict[str, Any]] | None, node: str, event: str, **payload: Any) -> list[dict[str, Any]]:
    events = list(state_events or [])
    events.append(RunEvent(node=node, event=event, payload=payload).model_dump(mode="json"))
    return events
