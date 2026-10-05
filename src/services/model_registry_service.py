"""Model registry and multi-provider fallback execution service.

Orchestrates LLM generation, vector embeddings, and multimodal inspection
across OpenAI-compatible and Anthropic endpoints with priority fallback chains.
"""

import base64
import logging
from typing import Any

import httpx
from openai import OpenAI

from src.core.config import settings
from src.models.schemas import ModelDefinition
from src.repositories.action_log_repository import ActionLogRepository
from src.repositories.cost_repository import CostRepository

logger = logging.getLogger(__name__)


class ModelRegistryService:
    """Dispatches AI tasks across configured provider models with ordered fallback chains."""

    def __init__(
        self,
        action_log_repo: ActionLogRepository | None = None,
        cost_repo: CostRepository | None = None,
    ) -> None:
        self.action_log_repo = action_log_repo
        self.cost_repo = cost_repo

    def normalize_embedding_url(self, base_url: str | None) -> str:
        """Normalize conversational endpoint URLs to embeddings-compatible base root."""
        if not base_url:
            raw_litellm = (settings.litellm_base_url or "http://localhost:4000").rstrip("/")
            return raw_litellm if raw_litellm.endswith("/v1") else f"{raw_litellm}/v1"

        cleaned = base_url.rstrip("/")
        # If url explicitly ends in chat or completions, strip to the base API root
        for suffix in ["/chat/completions", "/completions", "/chat"]:
            if cleaned.endswith(suffix):
                cleaned = cleaned[: -len(suffix)]

        if "googleapis.com" in cleaned:
            return cleaned if cleaned.endswith("/openai") else f"{cleaned}/openai"

        return cleaned if cleaned.endswith("/v1") else f"{cleaned}/v1"

    def _resolve_openai_client(self, model_def: ModelDefinition) -> OpenAI:
        """Instantiate an OpenAI-compatible client for the given model definition."""
        base_url = model_def.base_url
        if model_def.endpoint_type == "embedding":
            effective_base = self.normalize_embedding_url(base_url)
        elif base_url:
            raw = base_url.rstrip("/")
            if "googleapis.com" in raw:
                effective_base = raw if raw.endswith("/openai") else f"{raw}/openai"
            else:
                effective_base = raw if raw.endswith("/v1") else f"{raw}/v1"
        else:
            raw_default = (settings.litellm_base_url or "http://localhost:4000").rstrip("/")
            effective_base = raw_default if raw_default.endswith("/v1") else f"{raw_default}/v1"

        effective_key = model_def.api_key or "sk-dummy"
        return OpenAI(
            base_url=effective_base,
            api_key=effective_key,
            timeout=model_def.timeout,
            default_headers=model_def.extra_headers or None,
        )

    def call_chat_completion(
        self,
        model_def: ModelDefinition,
        messages: list[dict[str, Any]],
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> tuple[str, dict[str, Any]]:
        """Dispatch chat completion to OpenAI-compatible or Anthropic endpoint."""
        if model_def.api_format == "anthropic":
            return self._call_anthropic_chat(
                model_def=model_def,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )

        client = self._resolve_openai_client(model_def)
        kwargs: dict[str, Any] = {
            "model": model_def.model_name,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens

        resp = client.chat.completions.create(**kwargs)
        content = resp.choices[0].message.content or ""
        usage: dict[str, Any] = {}
        if getattr(resp, "usage", None):
            usage = {
                "prompt_tokens": getattr(resp.usage, "prompt_tokens", 0),
                "completion_tokens": getattr(resp.usage, "completion_tokens", 0),
                "total_tokens": getattr(resp.usage, "total_tokens", 0),
            }
        return content, usage

    def _call_anthropic_chat(
        self,
        model_def: ModelDefinition,
        messages: list[dict[str, Any]],
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> tuple[str, dict[str, Any]]:
        """Call Anthropic Messages API using standard HTTP transport."""
        base_url = (model_def.base_url or "https://api.anthropic.com").rstrip("/")
        if base_url.endswith("/v1/messages"):
            url = base_url
        elif base_url.endswith("/v1"):
            url = f"{base_url}/messages"
        else:
            url = f"{base_url}/v1/messages"

        headers = {
            "x-api-key": model_def.api_key or "",
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
            **model_def.extra_headers,
        }

        system_prompt = ""
        anthropic_messages: list[dict[str, Any]] = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                system_prompt = f"{system_prompt}\n{content}".strip()
            else:
                anthropic_messages.append({"role": role, "content": content})

        if not anthropic_messages:
            anthropic_messages.append({"role": "user", "content": "Execute instructions."})

        payload: dict[str, Any] = {
            "model": model_def.model_name,
            "messages": anthropic_messages,
            "max_tokens": max_tokens or 4096,
            "temperature": temperature,
        }
        if system_prompt:
            payload["system"] = system_prompt

        with httpx.Client(timeout=model_def.timeout) as http_client:
            response = http_client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()

        text_parts = [
            item.get("text", "") for item in data.get("content", []) if item.get("type") == "text"
        ]
        text_content = "".join(text_parts)
        usage_data = data.get("usage", {})
        usage = {
            "prompt_tokens": usage_data.get("input_tokens", 0),
            "completion_tokens": usage_data.get("output_tokens", 0),
            "total_tokens": usage_data.get("input_tokens", 0) + usage_data.get("output_tokens", 0),
        }
        return text_content, usage

    def call_embedding(
        self,
        model_def: ModelDefinition,
        texts: list[str],
    ) -> list[list[float]]:
        """Generate dense vector embeddings using local fastembed or remote API."""
        m_lower = model_def.model_name.lower()
        if (
            m_lower.startswith("local")
            or m_lower.startswith("fastembed")
            or "bge-small" in m_lower
            or "all-minilm" in m_lower
            or "bge-base" in m_lower
        ):
            from fastembed import TextEmbedding

            hf_model = (
                model_def.model_name.split(":", 1)[1]
                if ":" in model_def.model_name
                else "BAAI/bge-small-en-v1.5"
            )
            embedding_model = TextEmbedding(model_name=hf_model)
            embeddings = list(embedding_model.embed(texts))
            return [emb.tolist() for emb in embeddings]

        client = self._resolve_openai_client(model_def)
        resp = client.embeddings.create(input=texts, model=model_def.model_name)
        return [item.embedding for item in resp.data]

    def call_multimodal(
        self,
        model_def: ModelDefinition,
        text_prompt: str,
        image_bytes: bytes,
        mime_type: str = "image/jpeg",
        system_instruction: str = "",
    ) -> str:
        """Call multimodal visual model to evaluate an image frame."""
        if model_def.api_format == "anthropic":
            b64_image = base64.b64encode(image_bytes).decode("utf-8")
            messages = [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": mime_type,
                                "data": b64_image,
                            },
                        },
                        {"type": "text", "text": text_prompt},
                    ],
                }
            ]
            if system_instruction:
                messages.insert(0, {"role": "system", "content": system_instruction})
            text, _ = self.call_chat_completion(model_def, messages)
            return text

        # OpenAI / Gemini OpenAI format
        b64_image = base64.b64encode(image_bytes).decode("utf-8")
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": text_prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime_type};base64,{b64_image}"},
                    },
                ],
            }
        ]
        if system_instruction:
            messages.insert(0, {"role": "system", "content": system_instruction})
        text, _ = self.call_chat_completion(model_def, messages)
        return text

    def execute_role_fallback_chat(
        self,
        role: str,
        messages: list[dict[str, Any]],
        model_override: str | None = None,
        job_id: int | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> tuple[str, str, ModelDefinition, dict[str, Any]]:
        """Iterate down a role's ordered fallback list until a model succeeds."""
        chain = settings.get_model_definitions_for_role(role)
        if model_override:
            override_def = settings.get_model_definition_by_name(model_override, role=role)
            # Place override at front of the chain, removing duplicate if already present
            chain = [override_def] + [m for m in chain if m.name != override_def.name]

        if not chain:
            raise RuntimeError(f"No configured models found for role '{role}'")

        errors: list[str] = []
        for idx, model_def in enumerate(chain):
            try:
                content, usage = self.call_chat_completion(
                    model_def=model_def,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                return content, model_def.model_name, model_def, usage
            except Exception as exc:
                err_msg = (
                    f"Model '{model_def.name}' ({model_def.model_name}) "
                    f"failed for role '{role}': {exc}"
                )
                logger.warning("%s. Falling back to next model.", err_msg)
                errors.append(err_msg)

                if self.action_log_repo:
                    try:
                        self.action_log_repo.record_action(
                            stage=f"{role}_fallback",
                            action="model_fallback",
                            status="warning",
                            message=err_msg,
                            job_id=job_id,
                            details={
                                "attempted_model": model_def.name,
                                "model_name": model_def.model_name,
                                "chain_index": idx,
                                "total_chain": len(chain),
                                "error": str(exc),
                            },
                        )
                    except Exception as log_err:
                        logger.warning("Failed to persist fallback action log: %s", log_err)

        joined_errors = "; ".join(errors)
        raise RuntimeError(
            f"All {len(chain)} configured models failed for role '{role}'. Errors: {joined_errors}"
        )

    def execute_role_fallback_embedding(
        self,
        texts: list[str],
        model_override: str | None = None,
        job_id: int | None = None,
    ) -> tuple[list[list[float]], str, ModelDefinition]:
        """Iterate down the embedding role's fallback list until embedding generation succeeds."""
        chain = settings.get_model_definitions_for_role("embedding")
        if model_override:
            override_def = settings.get_model_definition_by_name(model_override, role="embedding")
            chain = [override_def] + [m for m in chain if m.name != override_def.name]

        if not chain:
            raise RuntimeError("No configured models found for role 'embedding'")

        errors: list[str] = []
        for idx, model_def in enumerate(chain):
            try:
                embeddings = self.call_embedding(model_def=model_def, texts=texts)
                return embeddings, model_def.model_name, model_def
            except Exception as exc:
                err_msg = (
                    f"Embedding model '{model_def.name}' ({model_def.model_name}) failed: {exc}"
                )
                logger.warning("%s. Falling back to next model.", err_msg)
                errors.append(err_msg)

                if self.action_log_repo:
                    try:
                        self.action_log_repo.record_action(
                            stage="embedding_fallback",
                            action="model_fallback",
                            status="warning",
                            message=err_msg,
                            job_id=job_id,
                            details={
                                "attempted_model": model_def.name,
                                "model_name": model_def.model_name,
                                "chain_index": idx,
                                "total_chain": len(chain),
                                "error": str(exc),
                            },
                        )
                    except Exception as log_err:
                        logger.warning("Failed to persist fallback action log: %s", log_err)

        raise RuntimeError(
            f"All {len(chain)} configured embedding models failed. Errors: {'; '.join(errors)}"
        )

    def execute_role_fallback_vlm(
        self,
        text_prompt: str,
        image_bytes: bytes,
        mime_type: str = "image/jpeg",
        system_instruction: str = "",
        model_override: str | None = None,
        job_id: int | None = None,
    ) -> tuple[str, str, ModelDefinition]:
        """Iterate down the vlm_inspector role's fallback list until inspection succeeds."""
        chain = settings.get_model_definitions_for_role("vlm_inspector")
        if model_override:
            override_def = settings.get_model_definition_by_name(
                model_override, role="vlm_inspector"
            )
            chain = [override_def] + [m for m in chain if m.name != override_def.name]

        if not chain:
            raise RuntimeError("No configured models found for role 'vlm_inspector'")

        errors: list[str] = []
        for idx, model_def in enumerate(chain):
            try:
                result = self.call_multimodal(
                    model_def=model_def,
                    text_prompt=text_prompt,
                    image_bytes=image_bytes,
                    mime_type=mime_type,
                    system_instruction=system_instruction,
                )
                return result, model_def.model_name, model_def
            except Exception as exc:
                err_msg = f"VLM model '{model_def.name}' ({model_def.model_name}) failed: {exc}"
                logger.warning("%s. Falling back to next model.", err_msg)
                errors.append(err_msg)

                if self.action_log_repo:
                    try:
                        self.action_log_repo.record_action(
                            stage="vlm_fallback",
                            action="model_fallback",
                            status="warning",
                            message=err_msg,
                            job_id=job_id,
                            details={
                                "attempted_model": model_def.name,
                                "model_name": model_def.model_name,
                                "chain_index": idx,
                                "total_chain": len(chain),
                                "error": str(exc),
                            },
                        )
                    except Exception as log_err:
                        logger.warning("Failed to persist fallback action log: %s", log_err)

        raise RuntimeError(
            f"All {len(chain)} configured VLM models failed. Errors: {'; '.join(errors)}"
        )
