import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import merge_agents


class MergeAgentsTests(unittest.TestCase):
    def test_append_preserves_existing_global_rules(self):
        base = "# Existing global rules\n\nDo not replace me.\n"
        block = merge_agents.managed_block(Path("templates/AGENTS.nanomaid.md"))
        merged = merge_agents.merge_content(base, block)
        self.assertTrue(merged.startswith(base))
        self.assertEqual(merged.count(merge_agents.BEGIN), 1)
        self.assertEqual(merged.count(merge_agents.END), 1)
        self.assertEqual(merge_agents.merge_content(merged, block), merged)

    def test_update_replaces_only_managed_block(self):
        old = f"# Global\n\n{merge_agents.BEGIN}\nold NanoMaid block\n{merge_agents.END}\n\n# Local tail\n"
        block = merge_agents.managed_block(Path("templates/AGENTS.nanomaid.md"))
        merged = merge_agents.merge_content(old, block)
        self.assertTrue(merged.startswith("# Global\n\n"))
        self.assertTrue(merged.endswith("\n\n# Local tail\n"))
        self.assertIn("load the `colab` skill", merged)
        self.assertNotIn("old NanoMaid block", merged)

    def test_rejects_malformed_or_duplicate_markers(self):
        block = merge_agents.managed_block(Path("templates/AGENTS.nanomaid.md"))
        for bad in (f"{merge_agents.BEGIN}\nmissing end", f"{block}\n{block}"):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, "markers"):
                merge_agents.merge_content(bad, block)

    def test_install_is_idempotent_and_backs_up_existing_file(self):
        template = Path("templates/AGENTS.nanomaid.md").resolve()
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "AGENTS.md"
            target.write_text("# Existing global rules\n")
            target.chmod(0o640)
            argv = ["merge_agents.py", "install", "--target", str(target), "--template", str(template)]
            with patch("sys.argv", argv), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(merge_agents.main(), 0)
            self.assertEqual(target.stat().st_mode & 0o777, 0o640)
            self.assertIn("# Existing global rules", target.read_text())
            backups = list(Path(tmp).glob("AGENTS.md.nanomaid-*.bak"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].stat().st_mode & 0o777, 0o600)

            with patch("sys.argv", argv), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(merge_agents.main(), 0)
            self.assertEqual(len(list(Path(tmp).glob("AGENTS.md.nanomaid-*.bak"))), 1)

    def test_refuses_symlink_target(self):
        template = Path("templates/AGENTS.nanomaid.md").resolve()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            real = root / "real.md"
            real.write_text("user instructions\n")
            target = root / "AGENTS.md"
            target.symlink_to(real)
            argv = ["merge_agents.py", "install", "--target", str(target), "--template", str(template)]
            with patch("sys.argv", argv), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(merge_agents.main(), 1)
            self.assertEqual(real.read_text(), "user instructions\n")


if __name__ == "__main__":
    unittest.main()
