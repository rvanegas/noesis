import json

from config import ANTHROPIC_MODEL
from core.utils import logger
from services.openaiclient import client
from services.system_prompt import (
    gen_name_system_prompt,
    explain_system_prompt)


class AssistantResponseError(Exception):
    """Raised when the LLM doesn't return a valid response."""
    pass


class Gpt:
    def __init__(self, instructions: str, response_format_base: dict):
        self.instructions = instructions
        self.response_format_base = response_format_base

    def call(self, prompt: str, file_ids: list[str] | None) -> str:
        user_content: list = []

        if file_ids:
            for fid in file_ids:
                user_content.append({
                    "type": "document",
                    "source": {"type": "file", "file_id": fid}
                })

        user_content.append({"type": "text", "text": prompt})

        kwargs = dict(
            model=ANTHROPIC_MODEL,
            max_tokens=4096,
            system=self.instructions,
            messages=[{"role": "user", "content": user_content}],
            output_config={
                "format": {
                    "type": "json_schema",
                    "name": "response",
                    "schema": self.response_format_base
                }
            }
        )
        if file_ids:
            kwargs["betas"] = ["files-api-2025-04-14"]

        response = client.messages.create(**kwargs)

        for block in response.content:
            if block.type == "text":
                return block.text

        logger.error(f"No text block in response: {response.content}")
        raise AssistantResponseError("no text content in LLM response")


gpt_gen_name = Gpt(
    instructions=gen_name_system_prompt,
    response_format_base={
        "type": "object",
        "properties": {
            "name": {"type": "string"}
        },
        "required": ["name"],
        "additionalProperties": False
    }
)

gpt_explain = Gpt(
    instructions=explain_system_prompt,
    response_format_base={
        "type": "object",
        "properties": {
            "formalization": {
                "type": "array",
                "items": {"type": "string"}
            },
            "explanation": {"type": "string"}
        },
        "required": ["formalization", "explanation"],
        "additionalProperties": False
    }
)
