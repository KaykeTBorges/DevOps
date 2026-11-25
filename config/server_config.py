"""Configuração centralizada do AI Compute Server.

Todas as configurações administrativas ficam aqui. Apenas o administrador
do servidor deve alterar estes valores. Os usuários NÃO controlam recursos
de hardware — somente o timeout de execução (dentro do teto definido abaixo).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Pilar 1 — Autenticação (domínios permitidos)
# ---------------------------------------------------------------------------
ALLOWED_EMAIL_DOMAINS: list[str] = [
    "academico.ufpb.br",
]

DEV_AUTH_MOCK: bool = os.environ.get("DEV_AUTH_MOCK", "false").lower() in ("true", "1", "yes")
OTP_EXPIRATION_SECONDS: int = int(os.environ.get("OTP_EXPIRATION_SECONDS", "900"))  # 15 minutos
OTP_REQUEST_INTERVAL_SECONDS: int = int(os.environ.get("OTP_REQUEST_INTERVAL_SECONDS", "60"))
OTP_MAX_ATTEMPTS: int = int(os.environ.get("OTP_MAX_ATTEMPTS", "5"))
TOKEN_EXPIRATION_DAYS: int = int(os.environ.get("TOKEN_EXPIRATION_DAYS", "7"))


def validate_email_domain(email: str) -> tuple[bool, str]:
    """Valida se o e-mail pertence a um dos domínios institucionais autorizados."""
    email = (email or "").strip().lower()
    if not email or "@" not in email:
        return False, "E-mail inválido ou vazio."

    domain = email.split("@", 1)[1]
    if domain in ALLOWED_EMAIL_DOMAINS:
        return True, "E-mail institucional autorizado."

    return False, (
        f"Domínio '@{domain}' não autorizado. Apenas e-mails institucionais autorizados "
        f"({', '.join('@' + d for d in ALLOWED_EMAIL_DOMAINS)}) são permitidos."
    )

# ---------------------------------------------------------------------------
# Pilar 2 — Catálogo de Imagens Docker (Allowlist)
# ---------------------------------------------------------------------------
# Cada entrada é um dicionário com:
#   id            — identificador curto e único (usado na API)
#   display_name  — nome amigável mostrado no frontend
#   image_tag     — tag completa da imagem Docker
#   description   — breve descrição do ambiente
#   gpu_required  — se a imagem requer GPU
#   is_active     — se está disponível para uso
IMAGE_CATALOG: list[dict[str, Any]] = [
    {
        "id": "python311",
        "display_name": "Python 3.11 Base",
        "image_tag": "python:3.11-slim",
        "description": "Ambiente Python 3.11 mínimo, sem GPU. Ideal para scripts leves e pré-processamento.",
        "gpu_required": False,
        "is_active": True,
    },
    {
        "id": "python312",
        "display_name": "Python 3.12 Base",
        "image_tag": "python:3.12-slim",
        "description": "Ambiente Python 3.12 mínimo, sem GPU. Ideal para scripts leves e pré-processamento.",
        "gpu_required": False,
        "is_active": True,
    },
    {
        "id": "pytorch24-cuda124",
        "display_name": "PyTorch 2.4 + CUDA 12.4",
        "image_tag": "pytorch/pytorch:2.4.0-cuda12.4-cudnn9-runtime",
        "description": "PyTorch 2.4 com suporte a GPU CUDA 12.4. Para treinamento e inferência de modelos.",
        "gpu_required": True,
        "is_active": True,
    },
    {
        "id": "tensorflow216",
        "display_name": "TensorFlow 2.16",
        "image_tag": "tensorflow/tensorflow:2.16.1-gpu",
        "description": "TensorFlow 2.16 com suporte a GPU. Para modelos Keras e TF.",
        "gpu_required": True,
        "is_active": True,
    },
    {
        "id": "scipy-ml",
        "display_name": "SciPy / ML Clássico",
        "image_tag": "python:3.12-slim",
        "description": "Ambiente para Machine Learning clássico (scikit-learn, pandas, numpy). Sem GPU.",
        "gpu_required": False,
        "is_active": True,
    },
]

# ---------------------------------------------------------------------------
# Pilar 3 — Alocação de Recursos e Time-Boxing
# ---------------------------------------------------------------------------
# Recursos de hardware (definidos exclusivamente pelo admin)
SERVER_CPUS: str = os.environ.get("SERVER_CPUS", "4.0")
SERVER_MEMORY: str = os.environ.get("SERVER_MEMORY", "16g")
SERVER_GPU_COUNT: int = int(os.environ.get("SERVER_GPU_COUNT", "0"))
SERVER_GPU_DEVICE: str | None = os.environ.get("SERVER_GPU_DEVICE", None)

# Timeout
ADMIN_HARD_CAP_TIMEOUT: int = int(os.environ.get("ADMIN_HARD_CAP_TIMEOUT", "14400"))  # 4 horas em segundos
MIN_TIMEOUT: int = int(os.environ.get("MIN_TIMEOUT", "60"))  # 1 minuto mínimo
DEFAULT_TIMEOUT: int = int(os.environ.get("DEFAULT_TIMEOUT", "300"))  # 5 minutos padrão

# Anti-starvation: máximo de jobs por usuário na fila (pending + queued + running)
MAX_QUEUED_JOBS_PER_USER: int = int(os.environ.get("MAX_QUEUED_JOBS_PER_USER", "2"))


# ---------------------------------------------------------------------------
# Funções auxiliares
# ---------------------------------------------------------------------------

def get_active_images() -> list[dict[str, Any]]:
    """Retorna apenas as imagens ativas do catálogo."""
    return [img for img in IMAGE_CATALOG if img.get("is_active", True)]


def get_image_by_id(image_id: str) -> dict[str, Any] | None:
    """Busca uma imagem ativa pelo ID. Retorna None se não encontrada ou inativa."""
    for img in IMAGE_CATALOG:
        if img["id"] == image_id and img.get("is_active", True):
            return img
    return None


def validate_image_id(image_id: str) -> tuple[bool, str]:
    """Valida se um image_id pertence à allowlist ativa.
    
    Retorna (True, image_tag) se válido, (False, mensagem_erro) se inválido.
    """
    image = get_image_by_id(image_id)
    if image is None:
        valid_ids = [img["id"] for img in get_active_images()]
        return False, (
            f"Imagem '{image_id}' não pertence ao catálogo aprovado. "
            f"IDs disponíveis: {', '.join(valid_ids)}"
        )
    return True, image["image_tag"]


def validate_timeout(requested_seconds: int | None) -> tuple[int, str]:
    """Valida e normaliza o timeout solicitado pelo usuário.
    
    Retorna (applied_timeout, mensagem) onde applied_timeout é o valor
    efetivamente aplicado (capped pelo admin).
    """
    if requested_seconds is None:
        return DEFAULT_TIMEOUT, f"Timeout padrão aplicado: {DEFAULT_TIMEOUT}s"
    
    if requested_seconds < MIN_TIMEOUT:
        return MIN_TIMEOUT, (
            f"Timeout solicitado ({requested_seconds}s) abaixo do mínimo. "
            f"Ajustado para {MIN_TIMEOUT}s."
        )
    
    if requested_seconds > ADMIN_HARD_CAP_TIMEOUT:
        return ADMIN_HARD_CAP_TIMEOUT, (
            f"Timeout solicitado ({requested_seconds}s) excede o limite máximo do admin "
            f"({ADMIN_HARD_CAP_TIMEOUT}s = {ADMIN_HARD_CAP_TIMEOUT // 3600}h). "
            f"Ajustado para {ADMIN_HARD_CAP_TIMEOUT}s."
        )
    
    return requested_seconds, f"Timeout aceito: {requested_seconds}s"


def validate_user_quota(active_jobs_count: int) -> tuple[bool, str]:
    """Verifica se o usuário pode enfileirar mais jobs.
    
    Retorna (True, mensagem_ok) se pode, (False, mensagem_erro) se excedeu a cota.
    """
    if active_jobs_count >= MAX_QUEUED_JOBS_PER_USER:
        return False, (
            f"Cota de fila excedida: você já possui {active_jobs_count} job(s) "
            f"pendente(s)/em execução. Máximo permitido: {MAX_QUEUED_JOBS_PER_USER}. "
            f"Aguarde a finalização de um job antes de enviar outro."
        )
    return True, "Cota de fila OK"
