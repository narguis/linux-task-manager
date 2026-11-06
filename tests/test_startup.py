import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from linux_task_manager.startup import StartupManager


DESKTOP_ENTRY = """[Desktop Entry]
Type=Application
Name=Example App
Comment=Starts an example
Exec=example --background
"""


class StartupManagerTests(unittest.TestCase):
    def test_lists_and_disables_user_entry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config"
            autostart = config / "autostart"
            autostart.mkdir(parents=True)
            (autostart / "example.desktop").write_text(DESKTOP_ENTRY)
            with patch.dict(os.environ, {"XDG_CONFIG_DIRS": str(Path(directory) / "system")}):
                manager = StartupManager(config)
                entries = manager.list_entries()
                self.assertEqual(len(entries), 1)
                self.assertTrue(entries[0].enabled)
                result = manager.set_enabled(entries[0], False)
                self.assertTrue(result.ok)
                disabled = manager.list_entries()[0]
                self.assertFalse(disabled.enabled)

    def test_user_entry_overrides_system_entry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config"
            user_autostart = config / "autostart"
            system_autostart = root / "system" / "autostart"
            user_autostart.mkdir(parents=True)
            system_autostart.mkdir(parents=True)
            (system_autostart / "example.desktop").write_text(DESKTOP_ENTRY)
            (user_autostart / "example.desktop").write_text(
                DESKTOP_ENTRY.replace("Name=Example App", "Name=User Override")
            )
            with patch.dict(os.environ, {"XDG_CONFIG_DIRS": str(root / "system")}):
                entries = StartupManager(config).list_entries()
            self.assertEqual(entries[0].name, "User Override")
            self.assertEqual(entries[0].scope, "User")

    def test_key_editor_preserves_other_sections(self) -> None:
        text = DESKTOP_ENTRY + "\n[Desktop Action Test]\nName=Test\n"
        updated = StartupManager._set_desktop_key(text, "Hidden", "true")
        self.assertIn("Hidden=true", updated)
        self.assertIn("[Desktop Action Test]\nName=Test", updated)


if __name__ == "__main__":
    unittest.main()
