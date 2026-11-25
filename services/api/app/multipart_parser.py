"""Parser multipart/form-data puro utilizando a biblioteca padrão (email).

Substitui o módulo obsoleto 'cgi' (removido no Python 3.13), sem nenhuma
dependência externa.
"""

from __future__ import annotations

import email
from email.policy import default
from typing import Any


class MultipartFormData:
    """Representa os campos e arquivos extraídos de uma requisição multipart/form-data."""

    def __init__(self, fields: dict[str, str], files: dict[str, dict[str, Any]]):
        self.fields = fields
        self.files = files

    def getvalue(self, key: str, default_val: Any = None) -> Any:
        return self.fields.get(key, default_val)

    def getfile(self, key: str) -> dict[str, Any] | None:
        """Retorna dict com {'filename': str, 'content': bytes, 'content_type': str} ou None."""
        return self.files.get(key)


def parse_multipart(content_type_header: str, body_bytes: bytes) -> MultipartFormData:
    """Analisa o cabeçalho Content-Type e os bytes do corpo multipart.
    
    Retorna uma instância de MultipartFormData.
    """
    # Prepara o payload com cabeçalho MIME para o parser padrão
    mime_header = f"Content-Type: {content_type_header}\r\n\r\n".encode("utf-8")
    raw_message = mime_header + body_bytes

    msg = email.message_from_bytes(raw_message, policy=default)

    fields: dict[str, str] = {}
    files: dict[str, dict[str, Any]] = {}

    if msg.is_multipart():
        for part in msg.iter_parts():
            name = part.get_param("name", header="content-disposition")
            if not name:
                continue

            filename = part.get_filename()
            payload = part.get_payload(decode=True) or b""

            if filename is not None:
                files[name] = {
                    "filename": filename,
                    "content": payload,
                    "content_type": part.get_content_type(),
                }
            else:
                fields[name] = payload.decode("utf-8", errors="replace")

    return MultipartFormData(fields=fields, files=files)
