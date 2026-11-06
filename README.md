# Linux Task Manager

A native, installable task manager for Ubuntu and Debian. It is designed around the familiar Windows Task Manager workflow while using Linux-native process data, systemd, desktop startup entries, and authorization.

## Features

- **Processes summary:** CPU, memory, disk, and network cards include compact live graphs and split metric footers above the grouped process table.
- **Processes:** Search and sort every process; filter to your processes, desktop apps, or system processes. Related parent/child processes are grouped into expandable trees with application icons where available.
- **Process controls:** End task, force kill, suspend/resume, set priority, inspect details, copy the command, and open the executable location.
- **Performance:** Dark cyber-style 90-sample graphs for CPU, memory, disk activity, download, and upload, plus load average and uptime.
- **System:** Host, OS, kernel, desktop, CPU/core, GPU, memory, storage, firmware, and virtualization details in a dedicated hardware view.
- **Settings:** View software/version details, select the update speed, keep the window on top, activate `Ctrl+Shift+Esc`, and open the source repository.
- **History:** Session history by app or process group, including accumulated CPU, average CPU, peak memory, disk I/O, and last-seen time.
- **Startup apps:** View, enable, and disable freedesktop/GNOME autostart entries without changing system files.
- **Services:** View, start, and stop systemd services using the normal desktop administrator prompt.
- **Users:** See signed-in sessions and CPU, memory, and process totals by account.
- **Stable live list:** In-place updates, persistent expansion and scroll anchors, CPU-ranked processes by default, and a short-lived-process filter prevent distracting table churn.
- **Conveniences:** Selectable update speed, always-on-top mode, keyboard controls, dark native UI, and single-instance behavior.
- **Windows-style shortcut:** `Ctrl+Shift+Esc` is registered automatically on GNOME/Ubuntu, Cinnamon, and Xfce.

The application reads Linux `/proc` and `/sys` directly. It does not require `psutil`, a web runtime, a background daemon, or root access for normal monitoring.

## Install on Ubuntu or Debian

```bash
cd linux-task-manager
chmod +x install.sh uninstall.sh packaging/build-deb.sh linux-task-manager
./install.sh
```

The installer uses `sudo` only for package and application files. Run the script as your desktop user—not with `sudo ./install.sh`—so it can also register `Ctrl+Shift+Esc` for your session.

After installation, open **Linux Task Manager** from the app menu or press **Ctrl+Shift+Esc**.

### Build and install a `.deb`

```bash
./packaging/build-deb.sh
sudo apt install ./dist/linux-system-task-manager_0.4.2_all.deb
```

Open the app once after a `.deb` installation to register the desktop shortcut for your user.

### Uninstall

```bash
./uninstall.sh
```

## Run from source

Install the runtime packages:

```bash
sudo apt install python3 python3-gi python3-cairo python3-gi-cairo gir1.2-gtk-3.0 xdg-utils
python3 -m linux_task_manager
```

No virtual environment or Python package download is needed.

## Keyboard and mouse controls

| Control | Action |
|---|---|
| `Ctrl+Shift+Esc` | Open or focus Task Manager (after installation) |
| `Ctrl+F` | Focus search on Processes, Startup apps, or Services |
| `Delete` | End the selected process |
| `Shift+Delete` | Force-kill the selected process |
| Double-click process | Open process details |
| Right-click process | Open process action menu |

## Safety and Linux behavior

- Every process action verifies both the PID and process start time first, preventing an action from hitting a newly reused PID.
- **End task** sends `SIGTERM`, allowing a program to clean up. **Force kill** sends `SIGKILL` and can lose unsaved work.
- Processes owned by other users require Linux permissions not granted to the app. System services use PolicyKit/systemd authorization instead of running the whole UI as root.
- The **Apps** section matches running processes to installed `.desktop` launchers and then attaches child processes. Linux has no universal process-to-window registry, so unusual launchers may still appear under Background processes.
- On KDE Plasma, bind `Ctrl+Shift+Esc` to `linux-task-manager` in **System Settings → Keyboard → Shortcuts**. GNOME, Cinnamon, and Xfce are configured automatically.

## Development

```bash
make test
make check
make run
```

The monitoring, process-control, startup, and systemd modules are independent from GTK. Tests can exercise those interfaces without opening a display.

## License

MIT

The bundled Tux artwork is attributed to Larry Ewing and The GIMP, with vector
work by Simon Budig and Garrett LeSage. See
`linux_task_manager/resources/TUX-NOTICE.txt` for the redistribution notice.
