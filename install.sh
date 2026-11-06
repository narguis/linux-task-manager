#!/bin/sh
set -eu

PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
APP_DIR=/usr/lib/linux-task-manager
DESKTOP_ID=io.github.systemtaskmanager.TaskManager

if [ "$(id -u)" -eq 0 ]; then
  SUDO=""
else
  if ! command -v sudo >/dev/null 2>&1; then
    echo "sudo is required to install system files." >&2
    exit 1
  fi
  SUDO=sudo
fi

if command -v apt-get >/dev/null 2>&1; then
  echo "Installing required Ubuntu/Debian packages…"
  $SUDO apt-get install -y python3 python3-gi python3-cairo python3-gi-cairo gir1.2-gtk-3.0 xdg-utils
fi

echo "Installing Linux Task Manager…"
$SUDO install -d "$APP_DIR/linux_task_manager/resources"
$SUDO install -m 0644 "$PROJECT_DIR/linux_task_manager/"*.py "$APP_DIR/linux_task_manager/"
$SUDO install -m 0644 "$PROJECT_DIR/linux_task_manager/resources/style.css" "$APP_DIR/linux_task_manager/resources/style.css"
$SUDO install -m 0644 "$PROJECT_DIR/linux_task_manager/resources/tux.svg" "$APP_DIR/linux_task_manager/resources/tux.svg"
$SUDO install -m 0644 "$PROJECT_DIR/linux_task_manager/resources/TUX-NOTICE.txt" "$APP_DIR/linux_task_manager/resources/TUX-NOTICE.txt"
$SUDO install -m 0755 "$PROJECT_DIR/packaging/linux-task-manager" /usr/bin/linux-task-manager
$SUDO install -m 0644 "$PROJECT_DIR/packaging/$DESKTOP_ID.desktop" "/usr/share/applications/$DESKTOP_ID.desktop"
$SUDO install -d /usr/share/icons/hicolor/scalable/apps
$SUDO install -m 0644 "$PROJECT_DIR/packaging/$DESKTOP_ID.svg" "/usr/share/icons/hicolor/scalable/apps/$DESKTOP_ID.svg"
$SUDO install -d /usr/share/metainfo
$SUDO install -m 0644 "$PROJECT_DIR/packaging/$DESKTOP_ID.metainfo.xml" "/usr/share/metainfo/$DESKTOP_ID.metainfo.xml"

if command -v update-desktop-database >/dev/null 2>&1; then
  $SUDO update-desktop-database /usr/share/applications >/dev/null 2>&1 || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  $SUDO gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor >/dev/null 2>&1 || true
fi

if [ "$(id -u)" -ne 0 ] && [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; then
  linux-task-manager --install-shortcut || true
else
  echo "Open Linux Task Manager once from your desktop to register Ctrl+Shift+Esc."
fi

echo "Installation complete. Open 'Linux Task Manager' from the app menu."
