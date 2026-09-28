import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import merge_opencode_config


class MergeOpenCodeConfigTests(unittest.TestCase):
    def test_refuses_symlinked_config_without_changing_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp) / "opencode"
            config_dir.mkdir()
            target = config_dir / "user-config.json"
            original = '{"permissions": []}\n'
            target.write_text(original)
            config = config_dir / "opencode.json"
            config.symlink_to(target)

            with patch.dict(os.environ, {"XDG_CONFIG_HOME": tmp}), \
                 patch("sys.argv", ["merge_opencode_config.py"]), \
                 contextlib.redirect_stderr(io.StringIO()) as error:
                self.assertEqual(merge_opencode_config.main(), 1)

            self.assertTrue(config.is_symlink())
            self.assertEqual(target.read_text(), original)
            self.assertIn("Refusing to modify symlinked", error.getvalue())
            self.assertEqual(list(config_dir.glob("*.bak")), [])


if __name__ == "__main__":
    unittest.main()
