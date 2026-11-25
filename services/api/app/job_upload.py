from __future__ import annotations

import io
import os
import stat
import zipfile
from pathlib import Path


class ZipValidationError(ValueError):
    pass


class ZipSecurityValidator:
    MAX_SIZE_BYTES = 100 * 1024 * 1024
    MAX_FILES = 500
    MAX_UNCOMPRESSED_SIZE = 500 * 1024 * 1024
    MAX_DEPTH = 8

    @staticmethod
    def validate_file_size(file_size: int) -> None:
        if file_size <= 0:
            raise ZipValidationError("Arquivo ZIP vazio.")
        if file_size > ZipSecurityValidator.MAX_SIZE_BYTES:
            raise ZipValidationError(f"Arquivo ZIP excede o tamanho máximo permitido ({ZipSecurityValidator.MAX_SIZE_BYTES} bytes).")

    @staticmethod
    def validate_name(name: str) -> None:
        if not name or name in {".", ".."}:
            raise ZipValidationError(f"Nome inválido no ZIP: {name!r}")

        normalized = name.replace("\\", "/")
        if normalized.startswith("/"):
            raise ZipValidationError(f"Caminho absoluto proibido no ZIP: {name!r}")
        if ".." in normalized.split("/"):
            raise ZipValidationError(f"Path traversal detectado: {name!r}")
        if normalized.startswith("../") or normalized == "..":
            raise ZipValidationError(f"Path traversal detectado: {name!r}")

    @staticmethod
    def validate_entry(entry: zipfile.ZipInfo) -> None:
        if entry.is_dir():
            return

        if entry.filename.startswith("/"):
            raise ZipValidationError(f"Entrada absoluta proibida: {entry.filename!r}")

        if ".." in entry.filename.replace("\\", "/").split("/"):
            raise ZipValidationError(f"Path traversal detectado: {entry.filename!r}")

        if entry.external_attr >> 16 & 0o170000 == stat.S_IFLNK:
            raise ZipValidationError(f"Link simbólico proibido: {entry.filename!r}")

        if entry.file_size > 20 * 1024 * 1024:
            raise ZipValidationError(f"Arquivo individual muito grande: {entry.filename!r}")

        if len(entry.filename.split("/")) > ZipSecurityValidator.MAX_DEPTH:
            raise ZipValidationError(f"Profundidade de diretórios excedida: {entry.filename!r}")

    @staticmethod
    def safe_extract(zip_bytes: bytes, target_dir: str | Path) -> list[str]:
        target_root = Path(target_dir)
        target_root.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
            total_size = 0
            file_count = 0
            extracted: list[str] = []

            for info in archive.infolist():
                ZipSecurityValidator.validate_name(info.filename)
                ZipSecurityValidator.validate_entry(info)

                if info.is_dir():
                    continue

                total_size += info.file_size
                file_count += 1

                if file_count > ZipSecurityValidator.MAX_FILES:
                    raise ZipValidationError("Quantidade excessiva de arquivos no ZIP.")

                if total_size > ZipSecurityValidator.MAX_UNCOMPRESSED_SIZE:
                    raise ZipValidationError("ZIP excede o tamanho total descompactado permitido.")

                dest_path = target_root / info.filename
                dest_path.parent.mkdir(parents=True, exist_ok=True)

                if dest_path.exists() and dest_path.is_dir():
                    raise ZipValidationError(f"Entrada de diretório conflita com um arquivo: {info.filename!r}")

                # Rejeita arquivos ocultos em pastas sensíveis e sem necessidade.
                parts = dest_path.parts
                for part in parts:
                    if part.startswith('.') and part not in {'.', '..'}:
                        raise ZipValidationError(f"Arquivo oculto proibido: {info.filename!r}")

                with archive.open(info, "r") as src, open(dest_path, "wb") as dst:
                    chunk = src.read(1024 * 1024)
                    while chunk:
                        dst.write(chunk)
                        chunk = src.read(1024 * 1024)

                extracted.append(str(dest_path.relative_to(target_root)))

        return extracted
