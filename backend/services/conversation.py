# mypy: disable-error-code=call-overload
from dataclasses import dataclass
from typing import Optional
import threading
import time

from config import OPENAI_MODEL
from core.utils import logger
from services.openaiclient import client
from services.system_prompt import (
    gen_name_system_prompt,
    justify_system_prompt,
    evaluate_system_prompt,
    explain_system_prompt)

TTL = 24 * 60 * 60  # 24 hours

class AssistantResponseError(Exception):
    """Raised when the OpenAI assistant doesn't return a valid response."""
    pass

class VectorStoreInfo:
    def __init__(self, vector_store_id: str):
        self.vector_store_id = vector_store_id
        self.created_at = time.time()

    def is_expired(self) -> bool:
        return time.time() - self.created_at > TTL

class Gpt:
    # Class-level registry for vector stores
    _vector_store_registry = {}
    _vector_store_lock = threading.Lock()

    def __init__(self, instructions: str, response_format_base: str):
        self.instructions = instructions
        self.response_format_base = response_format_base
        self.assistant_id = None
        self.created_at = time.time()
        self.lock = threading.Lock()

    def get_assistant(self):
        with self.lock:
            if (self.assistant_id is None or
                (time.time() - self.created_at) > TTL):
                response_format = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "response",
                        "strict": True,
                        "schema": self.response_format_base
                    }
                }
                response = client.beta.assistants.create(
                    model=OPENAI_MODEL,
                    tools=[{"type": "file_search"}],
                    instructions=self.instructions,
                    response_format=response_format)
                self.assistant_id = response.id
                self.created_at = time.time()
            return self.assistant_id

    def get_vector_store(self, file_ids: list[str]) -> str:
        """Get or create a vector store for the given file IDs."""
        if not file_ids:
            return None

        # Create a frozen set of file IDs as the key
        file_ids_key = frozenset(file_ids)

        with self._vector_store_lock:
            current_time = time.time()

            # Check if we have a valid vector store for these file IDs
            if file_ids_key in self._vector_store_registry:
                logger.debug(f"vector store registry hit for {file_ids_key}")
                vs_info = self._vector_store_registry[file_ids_key]
                if not vs_info.is_expired():
                    return vs_info.vector_store_id
                else:
                    # Remove expired entry
                    logger.debug(f"vector store registry expired for {file_ids_key}")
                    del self._vector_store_registry[file_ids_key]

            # Create new vector store
            vs_response = client.vector_stores.create()
            for file_id in file_ids:
                client.vector_stores.files.create_and_poll(
                    vector_store_id=vs_response.id,
                    file_id=file_id)

            # Store in registry
            self._vector_store_registry[file_ids_key] = VectorStoreInfo(vs_response.id)

            return vs_response.id

    def call(self, prompt: str, file_ids: list[str] | None):
        assistant_id = self.get_assistant()
        thread={
            "messages": [{
                "role": "user",
                "content": prompt
            }]
        }
        # logger.debug(f"fids {file_ids}")

        if file_ids and len(file_ids) > 0:
            vector_store_id = self.get_vector_store(file_ids)
            if vector_store_id:
                thread["tool_resources"] = {
                    "file_search": {
                        "vector_store_ids": [vector_store_id]
                    }
                }

        run = client.beta.threads.create_and_run_poll(
            thread=thread,
            assistant_id=assistant_id,
        )
        messages = client.beta.threads.messages.list(
            thread_id=run.thread_id)
        # logger.debug(f"m {messages}")
        # raise AssistantResponseError("no assistant value found")
        for message in reversed(messages.data):
            if message.role == "assistant":
                return message.content[0].text.value
        logger.error(f"No assistant value found. Messages returned: {messages.data}")
        raise AssistantResponseError("no assistant value found")

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

# gpt_justify = Gpt(
#     instructions=justify_system_prompt,
#     response_format_base={
#         "type": "object",
#         "properties": {
#             "propositions": {
#                 "type": "array",
#                 "items": {"type": "string"}
#             }
#         },
#         "required": ["propositions"],
#         "additionalProperties": False
#     }
# )

# gpt_evaluate = Gpt(
#     instructions=evaluate_system_prompt,
#     response_format_base={
#         "type": "object",
#         "properties": {
#             "truth": {
#                 "type": "array",
#                 "items": {"type": "string"}
#             },
#             "valid": {"type": "string"}
#         },
#         "required": ["truth", "valid"],
#         "additionalProperties": False
#     }
# )

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

