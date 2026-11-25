"""Testes para config/server_config.py — Validações dos Pilares 2 e 3."""

import sys
import unittest
from pathlib import Path

# Ajusta o path para importar o módulo de config
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "config"))

from server_config import (
    ADMIN_HARD_CAP_TIMEOUT,
    DEFAULT_TIMEOUT,
    IMAGE_CATALOG,
    MAX_QUEUED_JOBS_PER_USER,
    MIN_TIMEOUT,
    get_active_images,
    get_image_by_id,
    validate_image_id,
    validate_timeout,
    validate_user_quota,
)


class TestImageCatalog(unittest.TestCase):
    """Testes do Pilar 2 — Allowlist de Imagens Docker."""

    def test_catalog_has_entries(self):
        """Catálogo deve ter pelo menos uma imagem."""
        self.assertGreater(len(IMAGE_CATALOG), 0)

    def test_get_active_images_returns_only_active(self):
        """get_active_images deve retornar apenas imagens com is_active=True."""
        active = get_active_images()
        for img in active:
            self.assertTrue(img["is_active"])

    def test_get_image_by_valid_id(self):
        """Buscar imagem por ID válido deve retornar o registro correto."""
        result = get_image_by_id("python312")
        self.assertIsNotNone(result)
        self.assertEqual(result["id"], "python312")
        self.assertEqual(result["image_tag"], "python:3.12-slim")

    def test_get_image_by_invalid_id(self):
        """Buscar imagem por ID inválido deve retornar None."""
        result = get_image_by_id("imagem_inexistente_xyz")
        self.assertIsNone(result)

    def test_validate_image_id_valid(self):
        """Validar ID de imagem válido deve retornar (True, tag)."""
        ok, tag = validate_image_id("pytorch24-cuda124")
        self.assertTrue(ok)
        self.assertIn("pytorch", tag)

    def test_validate_image_id_invalid(self):
        """Validar ID de imagem inválido deve retornar (False, mensagem)."""
        ok, msg = validate_image_id("docker.io/malicious/image:latest")
        self.assertFalse(ok)
        self.assertIn("não pertence ao catálogo", msg)

    def test_validate_image_id_arbitrary_tag_rejected(self):
        """Usuário NÃO pode enviar uma tag Docker arbitrária."""
        ok, msg = validate_image_id("ubuntu:22.04")
        self.assertFalse(ok)

    def test_all_catalog_entries_have_required_fields(self):
        """Cada entrada do catálogo deve ter todos os campos obrigatórios."""
        required = {"id", "display_name", "image_tag", "description", "gpu_required", "is_active"}
        for img in IMAGE_CATALOG:
            for field in required:
                self.assertIn(field, img, f"Campo '{field}' ausente na imagem {img.get('id', '?')}")


class TestTimeoutValidation(unittest.TestCase):
    """Testes do Pilar 3 — Time-Boxing."""

    def test_timeout_within_limits(self):
        """Timeout dentro dos limites deve ser aceito."""
        applied, msg = validate_timeout(600)
        self.assertEqual(applied, 600)
        self.assertIn("aceito", msg)

    def test_timeout_below_minimum_capped(self):
        """Timeout abaixo do mínimo deve ser ajustado para MIN_TIMEOUT."""
        applied, msg = validate_timeout(10)
        self.assertEqual(applied, MIN_TIMEOUT)
        self.assertIn("mínimo", msg)

    def test_timeout_above_hard_cap(self):
        """Timeout acima do hard cap deve ser ajustado para ADMIN_HARD_CAP_TIMEOUT."""
        applied, msg = validate_timeout(99999)
        self.assertEqual(applied, ADMIN_HARD_CAP_TIMEOUT)
        self.assertIn("limite máximo", msg)

    def test_timeout_none_uses_default(self):
        """Timeout None deve usar o padrão."""
        applied, msg = validate_timeout(None)
        self.assertEqual(applied, DEFAULT_TIMEOUT)
        self.assertIn("padrão", msg)

    def test_timeout_exact_minimum(self):
        """Timeout igual ao mínimo deve ser aceito."""
        applied, msg = validate_timeout(MIN_TIMEOUT)
        self.assertEqual(applied, MIN_TIMEOUT)

    def test_timeout_exact_hard_cap(self):
        """Timeout igual ao hard cap deve ser aceito."""
        applied, msg = validate_timeout(ADMIN_HARD_CAP_TIMEOUT)
        self.assertEqual(applied, ADMIN_HARD_CAP_TIMEOUT)


class TestUserQuota(unittest.TestCase):
    """Testes do Pilar 3 — Anti-Starvation (cota por usuário)."""

    def test_quota_ok_when_below_limit(self):
        """Usuário com menos jobs que o limite deve poder enfileirar."""
        ok, msg = validate_user_quota(0)
        self.assertTrue(ok)

    def test_quota_ok_one_below_limit(self):
        """Usuário com exatamente (limite - 1) jobs deve poder enfileirar."""
        ok, msg = validate_user_quota(MAX_QUEUED_JOBS_PER_USER - 1)
        self.assertTrue(ok)

    def test_quota_exceeded_at_limit(self):
        """Usuário com exatamente o limite de jobs deve ser bloqueado."""
        ok, msg = validate_user_quota(MAX_QUEUED_JOBS_PER_USER)
        self.assertFalse(ok)
        self.assertIn("Cota de fila excedida", msg)

    def test_quota_exceeded_above_limit(self):
        """Usuário com mais que o limite de jobs deve ser bloqueado."""
        ok, msg = validate_user_quota(MAX_QUEUED_JOBS_PER_USER + 5)
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
