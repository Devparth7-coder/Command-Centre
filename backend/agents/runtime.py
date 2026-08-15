"""Provider boundary for production agent orchestration.

The API's deterministic local graph implements the same ordered event contract.
A production LangGraph adapter should compile typed state nodes, emit events
through the configured broker, and persist checkpoints without exposing chain
of thought. Only observable summaries and tool boundaries belong in traces.
"""
from typing import AsyncIterator, Protocol, TypedDict

class RuntimeEvent(TypedDict):
    kind: str
    title: str
    detail: str
    progress: int

class AgentRuntime(Protocol):
    async def execute(self, prompt: str, agent_id: int) -> AsyncIterator[RuntimeEvent]: ...
