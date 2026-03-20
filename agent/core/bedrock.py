from __future__ import annotations

import asyncio
import json
import os
import threading
from dataclasses import dataclass
from typing import AsyncIterator, Literal

from agent.core.session import SessionState

StreamDeltaKind = Literal["reasoning", "reply"]


class BedrockUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class StreamDelta:
    kind: StreamDeltaKind
    text: str


@dataclass(frozen=True)
class BedrockConfig:
    region: str
    sonnet_model_id: str = "anthropic.claude-sonnet-4-20250514-v1:0"
    opus_model_id: str = "anthropic.claude-opus-4-20250514-v1:0"
    max_tokens: int = 4096

    @classmethod
    def from_env(cls) -> BedrockConfig | None:
        region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION")
        if not region:
            return None
        return cls(
            region=region,
            sonnet_model_id=os.getenv("BEDROCK_SONNET_MODEL_ID", cls.sonnet_model_id),
            opus_model_id=os.getenv("BEDROCK_OPUS_MODEL_ID", cls.opus_model_id),
            max_tokens=int(os.getenv("BEDROCK_MAX_TOKENS", str(cls.max_tokens))),
        )


class BedrockClient:
    def __init__(self, config: BedrockConfig | None = None) -> None:
        self.config = config or BedrockConfig.from_env()

    def is_configured(self) -> bool:
        return self.config is not None

    def model_id_for_state(self, state: SessionState) -> str:
        if self.config is None:
            raise BedrockUnavailable("AWS region is not configured.")
        return self.config.opus_model_id if state.model == "opus" else self.config.sonnet_model_id

    async def stream_conversation(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        state: SessionState,
    ) -> AsyncIterator[StreamDelta]:
        if self.config is None:
            raise BedrockUnavailable("Set AWS_REGION or AWS_DEFAULT_REGION before using Bedrock.")

        try:
            import boto3
        except ModuleNotFoundError as exc:
            raise BedrockUnavailable("boto3 is not installed in the active Python environment.") from exc

        queue: asyncio.Queue[tuple[str, str]] = asyncio.Queue()
        loop = asyncio.get_running_loop()
        config = self.config
        model_id = self.model_id_for_state(state)
        payload = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": config.max_tokens,
            "system": system_prompt,
            "messages": [
                {
                    "role": "user",
                    "content": [{"type": "text", "text": user_prompt}],
                }
            ],
        }
        if state.thinking_enabled:
            payload["thinking"] = {
                "type": "enabled",
                "budget_tokens": state.thinking_budget_tokens,
            }

        def worker() -> None:
            try:
                client = boto3.client("bedrock-runtime", region_name=config.region)
                response = client.invoke_model_with_response_stream(
                    modelId=model_id,
                    body=json.dumps(payload),
                    contentType="application/json",
                    accept="application/json",
                )
                for event in response.get("body", []):
                    chunk = event.get("chunk")
                    if not chunk:
                        continue
                    body = json.loads(chunk["bytes"].decode("utf-8"))
                    delta = self._decode_delta(body)
                    if delta is None:
                        continue
                    loop.call_soon_threadsafe(queue.put_nowait, ("delta", json.dumps(delta.__dict__)))
                loop.call_soon_threadsafe(queue.put_nowait, ("done", ""))
            except Exception as exc:  # pragma: no cover - depends on external AWS runtime
                loop.call_soon_threadsafe(queue.put_nowait, ("error", str(exc)))

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()

        while True:
            event_kind, raw = await queue.get()
            if event_kind == "done":
                return
            if event_kind == "error":
                raise BedrockUnavailable(raw)
            payload_dict = json.loads(raw)
            yield StreamDelta(kind=payload_dict["kind"], text=payload_dict["text"])

    def _decode_delta(self, body: dict[str, object]) -> StreamDelta | None:
        if body.get("type") != "content_block_delta":
            return None
        delta = body.get("delta")
        if not isinstance(delta, dict):
            return None
        delta_type = delta.get("type")
        if delta_type == "thinking_delta":
            return StreamDelta("reasoning", str(delta.get("thinking", "")))
        if delta_type == "text_delta":
            return StreamDelta("reply", str(delta.get("text", "")))
        return None
