from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

from . import __version__


def _parse_arguments(arguments: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="linux-task-manager",
        description="A native task and performance manager for Linux.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--install-shortcut", action="store_true")
    group.add_argument("--remove-shortcut", action="store_true")
    return parser.parse_args(arguments)


def main(arguments: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if arguments is None else arguments)
    options = _parse_arguments(arguments)
    if options.install_shortcut or options.remove_shortcut:
        from .shortcut import install_shortcut, remove_shortcut

        ok, message = (
            install_shortcut(force=True) if options.install_shortcut else remove_shortcut()
        )
        print(message)
        return 0 if ok else 1

    import gi

    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    gi.require_version("Gio", "2.0")
    from gi.repository import Gdk, Gio, Gtk

    class TaskManagerApplication(Gtk.Application):
        def __init__(self) -> None:
            super().__init__(
                application_id="io.github.systemtaskmanager.TaskManager",
                flags=Gio.ApplicationFlags.FLAGS_NONE,
            )

        def do_startup(self) -> None:
            Gtk.Application.do_startup(self)
            settings = Gtk.Settings.get_default()
            if settings:
                settings.set_property("gtk-application-prefer-dark-theme", True)
            provider = Gtk.CssProvider()
            css_path = Path(__file__).with_name("resources") / "style.css"
            provider.load_from_path(str(css_path))
            screen = Gdk.Screen.get_default()
            if screen:
                Gtk.StyleContext.add_provider_for_screen(
                    screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
                )

        def do_activate(self) -> None:
            windows = self.get_windows()
            if windows:
                windows[0].present()
                return
            if shutil.which("linux-task-manager"):
                try:
                    from .shortcut import install_shortcut

                    install_shortcut(force=False)
                except Exception:
                    pass
            from .window import MainWindow

            MainWindow(self)

    application = TaskManagerApplication()
    return int(application.run([sys.argv[0]]))


if __name__ == "__main__":
    raise SystemExit(main())
