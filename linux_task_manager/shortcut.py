from __future__ import annotations

import os
import shutil
import subprocess


SHORTCUT_PATH = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/system-task-manager/"
SHORTCUT_NAME = "Linux Task Manager"
SHORTCUT_BINDING = "<Control><Shift>Escape"


def _installed_command() -> str:
    return shutil.which("linux-task-manager") or os.path.abspath(os.sys.argv[0])


def install_shortcut(force: bool = True) -> tuple[bool, str]:
    """Register Ctrl+Shift+Esc with the active desktop when supported."""
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
    if "gnome" in desktop or "ubuntu" in desktop or "cinnamon" in desktop:
        result = _install_gsettings_shortcut(force)
        if result[0]:
            return result
    if "xfce" in desktop:
        return _install_xfce_shortcut()
    return (
        False,
        "Automatic shortcut setup supports GNOME, Cinnamon, and Xfce. "
        "Bind Ctrl+Shift+Esc to 'linux-task-manager' in your desktop keyboard settings.",
    )


def remove_shortcut() -> tuple[bool, str]:
    try:
        import gi

        gi.require_version("Gio", "2.0")
        from gi.repository import Gio
    except (ImportError, ValueError):
        return False, "GSettings support is not available."
    for base_schema, child_schema in _gsettings_candidates():
        if not _schema_exists(Gio, base_schema) or not _schema_exists(Gio, child_schema):
            continue
        settings = Gio.Settings.new(base_schema)
        paths = list(settings.get_strv("custom-keybindings"))
        if SHORTCUT_PATH in paths:
            paths.remove(SHORTCUT_PATH)
            settings.set_strv("custom-keybindings", paths)
            settings.apply()
        child = Gio.Settings.new_with_path(child_schema, SHORTCUT_PATH)
        child.reset("name")
        child.reset("command")
        child.reset("binding")
        child.apply()
    return True, "Task Manager keyboard shortcut removed."


def _install_gsettings_shortcut(force: bool) -> tuple[bool, str]:
    try:
        import gi

        gi.require_version("Gio", "2.0")
        from gi.repository import Gio
    except (ImportError, ValueError):
        return False, "GSettings support is not available."

    for base_schema, child_schema in _gsettings_candidates():
        if not _schema_exists(Gio, base_schema) or not _schema_exists(Gio, child_schema):
            continue
        settings = Gio.Settings.new(base_schema)
        paths = list(settings.get_strv("custom-keybindings"))
        already_installed = SHORTCUT_PATH in paths
        if not already_installed:
            paths.append(SHORTCUT_PATH)
            settings.set_strv("custom-keybindings", paths)
        if force or not already_installed:
            child = Gio.Settings.new_with_path(child_schema, SHORTCUT_PATH)
            child.set_string("name", SHORTCUT_NAME)
            child.set_string("command", _installed_command())
            child.set_string("binding", SHORTCUT_BINDING)
            child.apply()
        settings.apply()
        return True, "Ctrl+Shift+Esc now opens Linux Task Manager."
    return False, "A compatible GNOME or Cinnamon shortcut schema was not found."


def _install_xfce_shortcut() -> tuple[bool, str]:
    executable = shutil.which("xfconf-query")
    if not executable:
        return False, "xfconf-query is not installed."
    command = [
        executable,
        "--channel",
        "xfce4-keyboard-shortcuts",
        "--property",
        "/commands/custom/<Primary><Shift>Escape",
        "--create",
        "--type",
        "string",
        "--set",
        _installed_command(),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode == 0:
        return True, "Ctrl+Shift+Esc now opens Linux Task Manager."
    return False, (completed.stderr or "Could not configure the Xfce shortcut.").strip()


def _gsettings_candidates() -> tuple[tuple[str, str], ...]:
    return (
        (
            "org.gnome.settings-daemon.plugins.media-keys",
            "org.gnome.settings-daemon.plugins.media-keys.custom-keybinding",
        ),
        (
            "org.cinnamon.settings-daemon.plugins.media-keys",
            "org.cinnamon.settings-daemon.plugins.media-keys.custom-keybinding",
        ),
    )


def _schema_exists(gio: object, schema_name: str) -> bool:
    source = gio.SettingsSchemaSource.get_default()
    return bool(source and source.lookup(schema_name, True))
