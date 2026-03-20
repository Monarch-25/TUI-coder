from __future__ import annotations

import asyncio
import json
import os
import threading
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from agent.core.session import SessionState


class BedrockUnavailable(RuntimeError):
    pass


ReasoningCallback = Callable[[str], Awaitable[None]]


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


@dataclass(frozen=True)
class BedrockToolCall:
    tool_use_id: str
    name: str
    input: dict[str, Any]


@dataclass(frozen=True)
class BedrockRound:
    text: str
    stop_reason: str
    tool_calls: list[BedrockToolCall] = field(default_factory=list)
    assistant_blocks: list[dict[str, Any]] = field(default_factory=list)

    def assistant_content(self) -> list[dict[str, Any]]:
        if self.assistant_blocks:
            return list(self.assistant_blocks)
        content: list[dict[str, Any]] = []
        if self.text.strip():
            content.append({"type": "text", "text": self.text})
        for call in self.tool_calls:
            content.append(
                {
                    "type": "tool_use",
                    "id": call.tool_use_id,
                    "name": call.name,
                    "input": call.input,
                }
            )
        return content


class BedrockClient:
    def __init__(self, config: BedrockConfig | None = None) -> None:
        self.config = config or BedrockConfig.from_env()

    def is_configured(self) -> bool:
        return self.config is not None

    def model_id_for_state(self, state: SessionState) -> str:
        if self.config is None:
            raise BedrockUnavailable("AWS region is not configured.")
        return self.config.opus_model_id if state.model == "opus" else self.config.sonnet_model_id

    def build_payload(
        self,
        *,
        system_prompt: str,
        messages: list[dict[str, Any]],
        state: SessionState,
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        if self.config is None:
            raise BedrockUnavailable("Set AWS_REGION or AWS_DEFAULT_REGION before using Bedrock.")
        payload: dict[str, Any] = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": self.config.max_tokens,
            "system": system_prompt,
            "messages": messages,
        }
        if tools:
            payload["tools"] = tools
            payload["anthropic_beta"] = ["fine-grained-tool-streaming-2025-05-14"]
        if state.thinking_enabled:
            payload["thinking"] = {
                "type": "enabled",
                "budget_tokens": state.thinking_budget_tokens,
            }
        return payload

    async def run_tool_round(
        self,
        *,
        system_prompt: str,
        messages: list[dict[str, Any]],
        state: SessionState,
        tools: list[dict[str, Any]] | None = None,
        on_reasoning: ReasoningCallback | None = None,
    ) -> BedrockRound:
        if self.config is None:
            raise BedrockUnavailable("Set AWS_REGION or AWS_DEFAULT_REGION before using Bedrock.")

        try:
            import boto3
        except ModuleNotFoundError as exc:
            raise BedrockUnavailable("boto3 is not installed in the active Python environment.") from exc

        queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()
        loop = asyncio.get_running_loop()
        payload = self.build_payload(system_prompt=system_prompt, messages=messages, state=state, tools=tools)
        model_id = self.model_id_for_state(state)
        config = self.config

        def worker() -> None:
            try:
                client = boto3.client("bedrock-runtime", region_name=config.region)
                response = client.invoke_model_with_response_stream(
                    modelId=model_id,
                    body=json.dumps(payload),
                    contentType="application/json",
                    accept="application/json",
                )
                text_chunks: list[str] = []
                tool_calls: list[BedrockToolCall] = []
                assistant_blocks: list[dict[str, Any]] = []
                tool_buffers: dict[int, dict[str, Any]] = {}
                stop_reason = "end_turn"

                for event in response.get("body", []):
                    chunk = event.get("chunk")
                    if not chunk:
                        continue
                    body = json.loads(chunk["bytes"].decode("utf-8"))
                    body_type = body.get("type")
                    if body_type == "content_block_start":
                        index = int(body.get("index", 0))
                        block = body.get("content_block")
                        if isinstance(block, dict):
                            block_type = str(block.get("type", ""))
                            if block_type == "tool_use":
                                tool_buffers[index] = {
                                    "type": "tool_use",
                                    "id": str(block.get("id", "")),
                                    "name": str(block.get("name", "")),
                                    "input": block.get("input"),
                                    "input_text": "" if block.get("input") is None else json.dumps(block.get("input")),
                                }
                            elif block_type == "thinking":
                                tool_buffers[index] = {
                                    "type": "thinking",
                                    "thinking": str(block.get("thinking", "")),
                                    "signature": str(block.get("signature", "")),
                                }
                            elif block_type == "text":
                                tool_buffers[index] = {
                                    "type": "text",
                                    "text": str(block.get("text", "")),
                                }
                    elif body_type == "content_block_delta":
                        index = int(body.get("index", 0))
                        delta = body.get("delta")
                        if not isinstance(delta, dict):
                            continue
                        delta_type = delta.get("type")
                        if delta_type == "thinking_delta":
                            buffer = tool_buffers.setdefault(index, {"type": "thinking", "thinking": "", "signature": ""})
                            buffer["thinking"] = str(buffer.get("thinking", "")) + str(delta.get("thinking", ""))
                            loop.call_soon_threadsafe(queue.put_nowait, ("reasoning", str(delta.get("thinking", ""))))
                        elif delta_type == "text_delta":
                            buffer = tool_buffers.setdefault(index, {"type": "text", "text": ""})
                            buffer["text"] = str(buffer.get("text", "")) + str(delta.get("text", ""))
                        elif delta_type == "input_json_delta":
                            buffer = tool_buffers.setdefault(
                                index,
                                {"type": "tool_use", "id": "", "name": "", "input_text": "", "input": None},
                            )
                            buffer["input_text"] = str(buffer.get("input_text", "")) + str(delta.get("partial_json", ""))
                        elif delta_type == "signature_delta":
                            buffer = tool_buffers.setdefault(index, {"type": "thinking", "thinking": "", "signature": ""})
                            buffer["signature"] = str(buffer.get("signature", "")) + str(delta.get("signature", ""))
                    elif body_type == "content_block_stop":
                        index = int(body.get("index", 0))
                        buffer = tool_buffers.pop(index, None)
                        if not buffer:
                            continue
                        buffer_type = str(buffer.get("type", ""))
                        if buffer_type == "text":
                            text = str(buffer.get("text", ""))
                            text_chunks.append(text)
                            assistant_blocks.append({"type": "text", "text": text})
                        elif buffer_type == "thinking":
                            thinking_block = {
                                "type": "thinking",
                                "thinking": str(buffer.get("thinking", "")),
                            }
                            signature = str(buffer.get("signature", ""))
                            if signature:
                                thinking_block["signature"] = signature
                            assistant_blocks.append(thinking_block)
                        elif buffer_type == "tool_use" and buffer.get("name"):
                            if isinstance(buffer.get("input"), dict):
                                input_payload = buffer["input"]
                            else:
                                raw_input = str(buffer.get("input_text", "")).strip()
                                try:
                                    input_payload = json.loads(raw_input or "{}")
                                except json.JSONDecodeError:
                                    input_payload = {"raw_input": raw_input}
                            tool_call = BedrockToolCall(
                                tool_use_id=str(buffer.get("id", "")),
                                name=str(buffer.get("name", "")),
                                input=input_payload,
                            )
                            tool_calls.append(tool_call)
                            assistant_blocks.append(
                                {
                                    "type": "tool_use",
                                    "id": tool_call.tool_use_id,
                                    "name": tool_call.name,
                                    "input": tool_call.input,
                                }
                            )
                    elif body_type == "message_delta":
                        delta = body.get("delta")
                        if isinstance(delta, dict) and delta.get("stop_reason"):
                            stop_reason = str(delta["stop_reason"])

                round_result = BedrockRound(
                    text="".join(text_chunks),
                    stop_reason=stop_reason,
                    tool_calls=tool_calls,
                    assistant_blocks=assistant_blocks,
                )
                loop.call_soon_threadsafe(queue.put_nowait, ("done", round_result))
            except Exception as exc:  # pragma: no cover - depends on external AWS runtime
                loop.call_soon_threadsafe(queue.put_nowait, ("error", str(exc)))

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()

        while True:
            event_kind, payload_item = await queue.get()
            if event_kind == "reasoning":
                if on_reasoning is not None and payload_item:
                    await on_reasoning(str(payload_item))
                continue
            if event_kind == "done":
                return payload_item
            if event_kind == "error":
                raise BedrockUnavailable(str(payload_item))
