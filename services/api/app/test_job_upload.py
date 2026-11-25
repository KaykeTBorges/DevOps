import os
import stat
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from job_upload import ZipSecurityValidator, ZipValidationError


class JobUploadTests(unittest.TestCase):
    def _zip_bytes(self, file_map):
        buffer = __import__("io").BytesIO()
        with zipfile.ZipFile(buffer, "w") as zf:
            for name, content in file_map.items():
                zf.writestr(name, content)
        return buffer.getvalue()

    def test_valid_zip_extracts_safely(self):
        payload = {"main.py": "print('ok')\n", "config/settings.json": '{"mode": "demo"}\n'}
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "job_unpack"
            extracted = ZipSecurityValidator.safe_extract(self._zip_bytes(payload), target)
            self.assertTrue((target / "main.py").exists())
            self.assertEqual(len(extracted), 2)

    def test_rejects_path_traversal(self):
        payload = {"../../evil.txt": "bad"}
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ZipValidationError):
                ZipSecurityValidator.safe_extract(self._zip_bytes(payload), Path(tmp))

    def test_rejects_zip_bomb_like_structure(self):
        payload = {f"nested/{i}/file.txt": "A" * 1024 for i in range(700)}
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ZipValidationError):
                ZipSecurityValidator.safe_extract(self._zip_bytes(payload), Path(tmp))

    def test_rejects_symlink_entry(self):
        buffer = __import__("io").BytesIO()
        with zipfile.ZipFile(buffer, "w") as zf:
            info = zipfile.ZipInfo("link")
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            zf.writestr(info, "target")

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ZipValidationError):
                ZipSecurityValidator.safe_extract(buffer.getvalue(), Path(tmp))


if __name__ == "__main__":
    unittest.main()
