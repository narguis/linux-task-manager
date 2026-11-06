#!/bin/sh
set -eu

DESKTOP_ID=io.github.systemtaskmanager.TaskManager

if command -v linux-task-manager >/dev/null 2>&1 && [ "$(id -u)" -ne 0 ]; then
  linux-task-manager --remove-shortcut || true
fi

if [ "$(id -u)" -eq 0 ]; then
  SUDO=""
else
  SUDO=sudo
fi

$SUDO rm -rf /usr/lib/linux-task-manager
$SUDO rm -f /usr/bin/linux-task-manager
$SUDO rm -f "/usr/share/applications/$DESKTOP_ID.desktop"
$SUDO rm -f "/usr/share/icons/hicolor/scalable/apps/$DESKTOP_ID.svg"
$SUDO rm -f "/usr/share/metainfo/$DESKTOP_ID.metainfo.xml"

echo "Linux Task Manager was removed."
