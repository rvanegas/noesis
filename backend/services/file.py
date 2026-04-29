import json
from dataclasses import dataclass, asdict

from core.utils import logger
from services.openaiclient import client

@dataclass
class FileData:
    content: bytes
    filename: str

@dataclass
class FileRef:
    file_id: str
    filename: str

def create_file(file_data: FileData):
    f_response = client.beta.files.upload(
        file=(file_data.filename, file_data.content, "application/octet-stream"),
        betas=["files-api-2025-04-14"]
    )
    file_ref = FileRef(
        file_id=f_response.id,
        filename=f_response.filename)
    return json.dumps(asdict(file_ref))
