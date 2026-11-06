#!/bin/sh
set -eu

PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
VERSION=$(sed -n 's/^version = "\([^"]*\)"/\1/p' "$PROJECT_DIR/pyproject.toml" | head -n 1)
PACKAGE=linux-system-task-manager
STAGE=$(mktemp -d "${TMPDIR:-/tmp}/linux-task-manager.XXXXXX")
DEST="$PROJECT_DIR/dist/${PACKAGE}_${VERSION}_all.deb"
DESKTOP_ID=io.github.systemtaskmanager.TaskManager
trap 'rm -rf "$STAGE"' EXIT INT TERM

mkdir -p "$STAGE/DEBIAN"
mkdir -p "$STAGE/usr/lib/linux-task-manager/linux_task_manager/resources"
mkdir -p "$STAGE/usr/bin"
mkdir -p "$STAGE/usr/share/applications"
mkdir -p "$STAGE/usr/share/icons/hicolor/scalable/apps"
mkdir -p "$STAGE/usr/share/metainfo"

cat > "$STAGE/DEBIAN/control" <<EOF
Package: $PACKAGE
Version: $VERSION
Section: utils
Priority: optional
Architecture: all
Depends: python3 (>= 3.10), python3-gi, python3-cairo, python3-gi-cairo, gir1.2-gtk-3.0, xdg-utils
Maintainer: Linux Task Manager contributors
Description: Native task and performance manager for Linux
 View and control processes, startup applications, systemd services,
 user sessions, and live CPU, memory, disk, and network performance.
EOF

cat > "$STAGE/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database /usr/share/applications >/dev/null 2>&1 || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor >/dev/null 2>&1 || true
fi
exit 0
EOF
chmod 0755 "$STAGE/DEBIAN/postinst"

cp "$PROJECT_DIR/linux_task_manager/"*.py "$STAGE/usr/lib/linux-task-manager/linux_task_manager/"
cp "$PROJECT_DIR/linux_task_manager/resources/style.css" "$STAGE/usr/lib/linux-task-manager/linux_task_manager/resources/"
cp "$PROJECT_DIR/linux_task_manager/resources/tux.svg" "$STAGE/usr/lib/linux-task-manager/linux_task_manager/resources/"
cp "$PROJECT_DIR/linux_task_manager/resources/TUX-NOTICE.txt" "$STAGE/usr/lib/linux-task-manager/linux_task_manager/resources/"
install -m 0755 "$PROJECT_DIR/packaging/linux-task-manager" "$STAGE/usr/bin/linux-task-manager"
cp "$PROJECT_DIR/packaging/$DESKTOP_ID.desktop" "$STAGE/usr/share/applications/"
cp "$PROJECT_DIR/packaging/$DESKTOP_ID.svg" "$STAGE/usr/share/icons/hicolor/scalable/apps/"
cp "$PROJECT_DIR/packaging/$DESKTOP_ID.metainfo.xml" "$STAGE/usr/share/metainfo/"

find "$STAGE" -type d -exec chmod 0755 {} +
find "$STAGE" -type f -exec chmod 0644 {} +
chmod 0755 "$STAGE/DEBIAN/postinst" "$STAGE/usr/bin/linux-task-manager"

mkdir -p "$PROJECT_DIR/dist"
dpkg-deb --build --root-owner-group "$STAGE" "$DEST"
echo "Built $DEST"
