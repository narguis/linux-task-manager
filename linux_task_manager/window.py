from __future__ import annotations

import os
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk, Pango

from . import __version__
from .actions import ProcessController
from .formatting import (
    ellipsize_middle,
    format_bytes,
    format_percent,
    format_rate,
    format_uptime,
)
from .grouping import SECTION_ORDER, ProcessGroup, build_process_groups, filter_process_groups
from .history import ActivityHistory, HistoryRecord, HistorySample
from .icons import ProcessIconResolver
from .models import ActionResult, ProcessInfo, ServiceInfo, StartupEntry, SystemSnapshot
from .monitor import SystemMonitor, build_user_summary
from .process_labels import process_display_name
from .services import ServiceManager
from .stability import ProcessListStabilizer
from .startup import StartupManager
from .system_info import SystemInfo, collect_system_info
from .widgets import MetricCard, PerformanceCard, add_class, scrolled


PROJECT_URL = "https://github.com/narguis/linux-task-manager"


class MainWindow(Gtk.ApplicationWindow):
    PROCESS_OBJECT = 12
    PROCESS_KIND = 13
    STARTUP_OBJECT = 5
    SERVICE_OBJECT = 5

    def __init__(self, application: Gtk.Application) -> None:
        super().__init__(application=application, title="Linux Task Manager")
        self.set_default_size(1180, 760)
        self.set_size_request(900, 600)
        self.set_icon_name("io.github.systemtaskmanager.TaskManager")

        self.monitor = SystemMonitor()
        self.controller = ProcessController()
        self.startup_manager = StartupManager()
        self.service_manager = ServiceManager()
        self.icon_resolver = ProcessIconResolver()
        self.process_stabilizer = ProcessListStabilizer()
        self.activity_history = ActivityHistory()
        self.executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="task-manager")
        self.processes: list[ProcessInfo] = []
        self.process_groups: list[ProcessGroup] = []
        self.snapshot: SystemSnapshot | None = None
        self.services: list[ServiceInfo] = []
        self._refresh_pending = False
        self._services_pending = False
        self._services_loaded = False
        self._system_info_pending = False
        self._system_info_loaded = False
        self._refresh_interval = 1.0
        self._always_on_top = False
        self._last_request = 0.0
        self._message_timer: int | None = None
        self._nav_buttons: dict[str, Gtk.RadioButton] = {}
        self._process_row_iters: dict[tuple[int, int], Gtk.TreeIter] = {}
        self._process_group_iters: dict[tuple[int, int], Gtk.TreeIter] = {}
        self._process_section_iters: dict[str, Gtk.TreeIter] = {}
        self._process_sort_columns: dict[int, Gtk.TreeViewColumn] = {}
        self._process_sort_column = 5
        self._process_sort_order = Gtk.SortType.DESCENDING
        self._process_structure: tuple[tuple[object, ...], ...] = ()
        self._last_process_structure_update = 0.0
        self._expanded_process_groups: set[tuple[int, int]] = set()
        self._rebuilding_process_model = False
        self._history_row_iters: dict[str, Gtk.TreeIter] = {}
        self._latest_history_records: list[HistoryRecord] = []
        self._last_users_update = 0.0

        self._build_header()
        self._build_layout()
        self.connect("destroy", self._on_destroy)
        self.connect("key-press-event", self._on_window_key_press)
        self.show_all()
        self.info_bar.hide()
        self._load_startup_entries()
        GLib.idle_add(self._request_refresh, True)
        GLib.timeout_add(400, self._refresh_tick)

    def _build_header(self) -> None:
        header = Gtk.HeaderBar()
        header.set_show_close_button(True)
        self.set_titlebar(header)

        brand = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        mark = Gtk.Label(label="//")
        add_class(mark, "header-mark")
        mark.set_tooltip_text("Linux Task Manager")
        penguin_path = Path(__file__).with_name("resources") / "tux.svg"
        penguin_pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(
            str(penguin_path), 28, 32, True
        )
        penguin = Gtk.Image.new_from_pixbuf(penguin_pixbuf)
        penguin.set_tooltip_text("Tux")
        add_class(penguin, "header-penguin")
        title = Gtk.Label(label="TASK MANAGER")
        add_class(title, "header-title")
        brand.pack_start(mark, False, False, 0)
        brand.pack_start(penguin, False, False, 0)
        brand.pack_start(title, False, False, 0)
        header.pack_start(brand)

        menu_button = Gtk.MenuButton()
        menu_button.add(Gtk.Label(label="•••"))
        add_class(menu_button, "minimal-menu")
        menu_button.set_tooltip_text("Task Manager options")
        menu_button.set_popup(self._build_options_menu())
        header.pack_end(menu_button)

    def _build_options_menu(self) -> Gtk.Menu:
        menu = Gtk.Menu()
        speed_item = Gtk.MenuItem(label="Update speed")
        speed_menu = Gtk.Menu()
        self._speed_menu_items: dict[float, Gtk.RadioMenuItem] = {}
        for label, seconds in (("High (0.5 s)", 0.5), ("Normal (1 s)", 1.0), ("Low (3 s)", 3.0)):
            item = Gtk.RadioMenuItem.new_with_label_from_widget(
                None if not speed_menu.get_children() else speed_menu.get_children()[0], label
            )
            item.set_active(seconds == 1.0)
            item.connect("activate", self._set_refresh_speed, seconds)
            speed_menu.append(item)
            self._speed_menu_items[seconds] = item
        speed_item.set_submenu(speed_menu)
        menu.append(speed_item)

        self.always_on_top_menu_item = Gtk.CheckMenuItem(label="Always on top")
        self.always_on_top_menu_item.connect(
            "toggled", lambda item: self._set_always_on_top(item.get_active())
        )
        menu.append(self.always_on_top_menu_item)

        shortcut_item = Gtk.MenuItem(label="Install Ctrl+Shift+Esc shortcut")
        shortcut_item.connect("activate", self._install_shortcut)
        menu.append(shortcut_item)

        about_item = Gtk.MenuItem(label="About")
        about_item.connect("activate", self._show_about)
        menu.append(about_item)
        menu.show_all()
        return menu

    def _build_layout(self) -> None:
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(root)

        self.info_bar = Gtk.InfoBar()
        self.info_label = Gtk.Label(label="", xalign=0)
        self.info_label.set_line_wrap(True)
        self.info_bar.get_content_area().add(self.info_label)
        self.info_bar.add_button("Dismiss", Gtk.ResponseType.CLOSE)
        self.info_bar.connect("response", lambda bar, _response: bar.hide())
        root.pack_start(self.info_bar, False, False, 0)

        body = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        root.pack_start(body, True, True, 0)

        navigation = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        navigation.set_size_request(205, -1)
        add_class(navigation, "navigation")
        body.pack_start(navigation, False, False, 0)

        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.stack.set_transition_duration(140)
        body.pack_start(self.stack, True, True, 0)

        pages = (
            ("processes", "Processes", "▦", self._build_processes_page()),
            ("performance", "Performance", "⌁", self._build_performance_page()),
            ("history", "History", "◷", self._build_history_page()),
            ("startup", "Startup apps", "↗", self._build_startup_page()),
            ("services", "Services", "◇", self._build_services_page()),
            ("system", "System", "▣", self._build_system_page()),
            ("users", "Users", "◎", self._build_users_page()),
            ("settings", "Settings", "⚙", self._build_settings_page()),
        )
        group: Gtk.RadioButton | None = None
        for name, label, glyph, page in pages:
            self.stack.add_named(page, name)
            button = Gtk.RadioButton.new_from_widget(group)
            if group is None:
                group = button
            button.set_mode(False)
            button.set_relief(Gtk.ReliefStyle.NONE)
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=11)
            glyph_label = Gtk.Label(label=glyph)
            glyph_label.set_size_request(24, 24)
            add_class(glyph_label, "nav-glyph")
            row.pack_start(glyph_label, False, False, 0)
            row.pack_start(Gtk.Label(label=label, xalign=0), True, True, 0)
            button.add(row)
            add_class(button, "nav-button")
            button.connect("toggled", self._navigate, name)
            navigation.pack_start(button, False, False, 0)
            self._nav_buttons[name] = button
        self._nav_buttons["processes"].set_active(True)
        self.stack.set_visible_child_name("processes")

        footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        add_class(footer, "version-footer")
        version_label = Gtk.Label(label=f"> linux-task-manager v{__version__}", xalign=0)
        add_class(version_label, "version-label")
        footer.pack_start(version_label, True, True, 0)
        root.pack_end(footer, False, False, 0)

    def _page(self, _title: str, _subtitle: str) -> Gtk.Box:
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        page.set_border_width(20)
        return page

    def _build_summary_cards(self) -> Gtk.Box:
        cards = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        cards.set_homogeneous(True)
        add_class(cards, "summary-cards")
        self.summary_cpu = MetricCard(
            "CPU",
            "red",
            show_graph=True,
            primary_color=(1.0, 0.25, 0.38),
        )
        self.summary_memory = MetricCard(
            "Memory",
            "purple",
            show_graph=True,
            primary_color=(0.68, 0.35, 1.0),
        )
        self.summary_disk = MetricCard(
            "Disk",
            "yellow",
            show_graph=True,
            primary_color=(1.0, 0.82, 0.22),
        )
        self.summary_network = MetricCard(
            "Network",
            "green",
            show_graph=True,
            graph_maximum=None,
            primary_color=(0.18, 0.92, 0.55),
            secondary_color=(0.68, 0.35, 1.0),
        )
        for card in (self.summary_cpu, self.summary_memory, self.summary_disk, self.summary_network):
            cards.pack_start(card, True, True, 0)
        return cards

    def _build_processes_page(self) -> Gtk.Widget:
        page = self._page(
            "Processes",
            "Inspect apps and background processes. End task asks programs to close; force kill is immediate.",
        )
        page.pack_start(self._build_summary_cards(), False, False, 0)
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.process_search = Gtk.SearchEntry()
        add_class(self.process_search, "process-search")
        self.process_search.set_placeholder_text("Search name, PID, user, or command")
        self.process_search.set_hexpand(True)
        self.process_search.connect(
            "search-changed", lambda _entry: self._rebuild_process_store(True)
        )
        toolbar.pack_start(self.process_search, True, True, 0)

        self.process_filter = Gtk.ComboBoxText()
        for item in ("All processes", "My processes", "Apps", "System processes"):
            self.process_filter.append_text(item)
        self.process_filter.set_active(0)
        self.process_filter.connect(
            "changed", lambda _combo: self._rebuild_process_store(True)
        )
        toolbar.pack_start(self.process_filter, False, False, 0)

        self.end_button = Gtk.Button(label="End task")
        add_class(self.end_button, "suggested-action")
        self.end_button.set_sensitive(False)
        self.end_button.connect("clicked", lambda _button: self._process_action("terminate"))
        toolbar.pack_start(self.end_button, False, False, 0)

        more = Gtk.MenuButton(label="More")
        more.set_popup(self._build_process_menu())
        toolbar.pack_start(more, False, False, 0)
        page.pack_start(toolbar, False, False, 0)

        self.process_store = Gtk.TreeStore(
            str, str, int, str, str, float, str, float, str, float, str, str, object, str, int
        )
        self.process_tree = Gtk.TreeView(model=self.process_store)
        self.process_tree.set_search_column(1)
        self.process_tree.set_enable_search(True)
        self.process_tree.set_rules_hint(True)
        self.process_tree.set_enable_tree_lines(True)
        self.process_tree.set_show_expanders(False)
        self.process_tree.set_level_indentation(4)
        self.process_tree.set_grid_lines(Gtk.TreeViewGridLines.BOTH)
        self.process_name_column = self._process_name_column()
        self._process_text_column("PID", 2, sort=2)
        self._process_text_column("CPU", 4, sort=5, align=1.0)
        self._process_text_column("Memory", 6, sort=7, align=1.0)
        self._process_text_column("Disk I/O", 8, sort=9, align=1.0)
        self._process_text_column("Status", 10, sort=10)
        command_column = self._process_text_column("Command", 11, sort=11, minimum=220)
        command_column.get_cells()[0].set_property("ellipsize", Pango.EllipsizeMode.END)
        self._process_text_column("User", 3, sort=3)
        for sort_column in (1, 2, 3, 5, 7, 9, 10, 11):
            self.process_store.set_sort_func(sort_column, self._process_sort_rows, sort_column)
        self._set_process_sort(5, Gtk.SortType.DESCENDING)
        self.process_tree.get_selection().connect("changed", self._process_selection_changed)
        self.process_tree.connect("row-activated", lambda *_args: self._show_process_details())
        self.process_tree.connect("button-press-event", self._process_context_event)
        self.process_tree.connect("key-press-event", self._process_key_event)
        self.process_tree.connect("row-expanded", self._process_row_expanded)
        self.process_tree.connect("row-collapsed", self._process_row_collapsed)
        self.process_scroll = scrolled(self.process_tree)
        page.pack_start(self.process_scroll, True, True, 0)
        return page

    def _build_process_menu(self) -> Gtk.Menu:
        menu = Gtk.Menu()
        actions = (
            ("Process details", lambda *_: self._show_process_details()),
            ("Open file location", lambda *_: self._process_action("open_location", confirm=False)),
            ("Suspend / resume", lambda *_: self._process_action("toggle_suspend", confirm=False)),
            ("Force kill", lambda *_: self._process_action("kill")),
        )
        for label, callback in actions:
            item = Gtk.MenuItem(label=label)
            item.connect("activate", callback)
            menu.append(item)
        priority = Gtk.MenuItem(label="Set priority")
        priority_menu = Gtk.Menu()
        for label, nice in (("High", -5), ("Normal", 0), ("Low", 10)):
            item = Gtk.MenuItem(label=label)
            item.connect("activate", lambda _item, value=nice: self._set_process_priority(value))
            priority_menu.append(item)
        priority.set_submenu(priority_menu)
        menu.append(priority)
        menu.show_all()
        self.process_context_menu = menu
        return menu

    def _build_performance_page(self) -> Gtk.Widget:
        page = self._page("Performance", "Live utilization over the last 90 updates.")
        grid = Gtk.Grid(column_spacing=12, row_spacing=12)
        grid.set_column_homogeneous(True)
        grid.set_row_homogeneous(True)
        self.cpu_card = PerformanceCard(
            "CPU", primary_color=(1.0, 0.25, 0.38)
        )
        add_class(self.cpu_card, "graph-red")
        self.memory_card = PerformanceCard(
            "Memory", primary_color=(0.68, 0.35, 1.0)
        )
        add_class(self.memory_card, "graph-purple")
        self.disk_card = PerformanceCard(
            "Disk activity", primary_color=(1.0, 0.82, 0.22)
        )
        add_class(self.disk_card, "graph-yellow")
        self.network_card = PerformanceCard(
            "Network",
            maximum=None,
            primary_color=(0.18, 0.92, 0.55),
            secondary_color=(0.68, 0.35, 1.0),
        )
        add_class(self.network_card, "graph-green")
        grid.attach(self.cpu_card, 0, 0, 1, 1)
        grid.attach(self.memory_card, 1, 0, 1, 1)
        grid.attach(self.disk_card, 0, 1, 1, 1)
        grid.attach(self.network_card, 1, 1, 1, 1)
        page.pack_start(grid, True, True, 0)

        details = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=24)
        add_class(details, "details-strip")
        self.performance_details: dict[str, Gtk.Label] = {}
        for name in ("Processor", "Cores", "Processes", "Threads", "Uptime", "Load average"):
            column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            caption = Gtk.Label(label=name, xalign=0)
            add_class(caption, "metric-detail")
            value = Gtk.Label(label="—", xalign=0)
            value.set_ellipsize(Pango.EllipsizeMode.END)
            value.set_max_width_chars(30 if name == "Processor" else 14)
            self.performance_details[name] = value
            column.pack_start(caption, False, False, 0)
            column.pack_start(value, False, False, 0)
            details.pack_start(column, name == "Processor", name == "Processor", 0)
        page.pack_end(details, False, False, 0)
        return scrolled(page)

    def _build_history_page(self) -> Gtk.Widget:
        page = self._page(
            "History",
            "Resource history accumulated while Task Manager is open. Short-lived process noise is grouped by app or parent process.",
        )
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.history_session_label = Gtk.Label(label="Session started just now", xalign=0)
        add_class(self.history_session_label, "page-subtitle")
        toolbar.pack_start(self.history_session_label, True, True, 0)
        clear_button = Gtk.Button(label="Clear history")
        clear_button.connect("clicked", self._clear_history)
        toolbar.pack_end(clear_button, False, False, 0)
        page.pack_start(toolbar, False, False, 0)

        cards = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        cards.set_homogeneous(True)
        self.history_groups_card = MetricCard("Tracked groups", "green")
        self.history_cpu_card = MetricCard("Accumulated CPU", "green")
        self.history_disk_card = MetricCard("Disk activity", "green")
        for card in (self.history_groups_card, self.history_cpu_card, self.history_disk_card):
            cards.pack_start(card, True, True, 0)
        page.pack_start(cards, False, False, 0)

        self.history_store = Gtk.ListStore(str, str, str, str, str, str, str)
        self.history_store.set_sort_column_id(1, Gtk.SortType.ASCENDING)
        self.history_tree = Gtk.TreeView(model=self.history_store)
        self._icon_text_column(self.history_tree, "App or process group", 0, 1, expand=True, minimum=230)
        self._text_column(self.history_tree, "CPU time", 2, align=1.0)
        self._text_column(self.history_tree, "Average CPU", 3, align=1.0)
        self._text_column(self.history_tree, "Peak memory", 4, align=1.0)
        self._text_column(self.history_tree, "Disk I/O", 5, align=1.0)
        self._text_column(self.history_tree, "Last seen", 6)
        page.pack_start(scrolled(self.history_tree), True, True, 0)
        self._history_started = time.time()
        return page

    def _build_startup_page(self) -> Gtk.Widget:
        page = self._page(
            "Startup apps", "Enable or disable programs that start automatically when you sign in."
        )
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.startup_search = Gtk.SearchEntry()
        self.startup_search.set_placeholder_text("Search startup apps")
        self.startup_search.set_hexpand(True)
        self.startup_search.connect("search-changed", lambda _entry: self._load_startup_entries())
        toolbar.pack_start(self.startup_search, True, True, 0)
        refresh = Gtk.Button(label="Refresh")
        refresh.connect("clicked", lambda _button: self._load_startup_entries())
        toolbar.pack_start(refresh, False, False, 0)
        self.startup_enable_button = Gtk.Button(label="Enable")
        self.startup_enable_button.set_sensitive(False)
        self.startup_enable_button.connect("clicked", lambda _button: self._set_startup_enabled(True))
        toolbar.pack_start(self.startup_enable_button, False, False, 0)
        self.startup_disable_button = Gtk.Button(label="Disable")
        self.startup_disable_button.set_sensitive(False)
        self.startup_disable_button.connect("clicked", lambda _button: self._set_startup_enabled(False))
        toolbar.pack_start(self.startup_disable_button, False, False, 0)
        page.pack_start(toolbar, False, False, 0)

        self.startup_store = Gtk.ListStore(str, str, str, str, str, object)
        self.startup_tree = Gtk.TreeView(model=self.startup_store)
        self._text_column(self.startup_tree, "Name", 0, expand=True, minimum=180)
        self._text_column(self.startup_tree, "Status", 1)
        self._text_column(self.startup_tree, "Command", 2, minimum=260)
        self._text_column(self.startup_tree, "Scope", 3)
        self._text_column(self.startup_tree, "Location", 4, minimum=180)
        self.startup_tree.get_selection().connect("changed", self._startup_selection_changed)
        page.pack_start(scrolled(self.startup_tree), True, True, 0)
        return page

    def _build_services_page(self) -> Gtk.Widget:
        page = self._page(
            "Services", "View and control systemd services. Changes may request administrator authorization."
        )
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.service_search = Gtk.SearchEntry()
        self.service_search.set_placeholder_text("Search services")
        self.service_search.set_hexpand(True)
        self.service_search.connect("search-changed", lambda _entry: self._rebuild_service_store())
        toolbar.pack_start(self.service_search, True, True, 0)
        refresh = Gtk.Button(label="Refresh")
        refresh.connect("clicked", lambda _button: self._refresh_services())
        toolbar.pack_start(refresh, False, False, 0)
        for label, action in (("Start", "start"), ("Stop", "stop")):
            button = Gtk.Button(label=label)
            button.set_sensitive(False)
            button.connect("clicked", lambda _button, selected=action: self._service_action(selected))
            toolbar.pack_start(button, False, False, 0)
            setattr(self, f"service_{action}_button", button)
        page.pack_start(toolbar, False, False, 0)

        self.service_store = Gtk.ListStore(str, str, str, str, str, object)
        self.service_tree = Gtk.TreeView(model=self.service_store)
        self._text_column(self.service_tree, "Service", 0, expand=True, minimum=220)
        self._text_column(self.service_tree, "Description", 1, minimum=280)
        self._text_column(self.service_tree, "Status", 2)
        self._text_column(self.service_tree, "Substate", 3)
        self._text_column(self.service_tree, "Startup", 4)
        self.service_tree.get_selection().connect("changed", self._service_selection_changed)
        page.pack_start(scrolled(self.service_tree), True, True, 0)
        return page

    def _build_system_page(self) -> Gtk.Widget:
        page = self._page(
            "System", "Hardware, operating system, firmware, and storage information."
        )

        hero = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        add_class(hero, "system-hero")
        heading = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        self.system_hostname = Gtk.Label(label="System information", xalign=0)
        add_class(self.system_hostname, "system-hostname")
        self.system_status = Gtk.Label(
            label="Open this page to detect hardware and operating system details.",
            xalign=0,
        )
        add_class(self.system_status, "system-status")
        heading.pack_start(self.system_hostname, False, False, 0)
        heading.pack_start(self.system_status, False, False, 0)
        hero.pack_start(heading, True, True, 0)
        refresh = Gtk.Button(label="Refresh system info")
        refresh.connect("clicked", lambda _button: self._load_system_info(force=True))
        hero.pack_end(refresh, False, False, 0)
        page.pack_start(hero, False, False, 0)

        self.system_labels: dict[str, Gtk.Label] = {}
        grid = Gtk.Grid(column_spacing=12, row_spacing=12)
        grid.set_column_homogeneous(True)
        panels = (
            (
                "Computer",
                (
                    ("manufacturer", "Manufacturer"),
                    ("model", "Model"),
                    ("firmware", "Firmware"),
                    ("virtualization", "Virtualization"),
                ),
            ),
            (
                "Operating system",
                (
                    ("os_name", "Distribution"),
                    ("kernel", "Kernel"),
                    ("architecture", "Architecture"),
                    ("desktop", "Desktop"),
                    ("session_type", "Display session"),
                ),
            ),
            (
                "Processor",
                (
                    ("cpu_model", "Processor"),
                    ("physical_cores", "Physical cores"),
                    ("logical_cores", "Logical processors"),
                    ("max_frequency", "Maximum frequency"),
                ),
            ),
            (
                "Memory",
                (
                    ("memory", "Installed memory"),
                    ("swap", "Swap"),
                ),
            ),
            ("Graphics", (("graphics", "Graphics devices"),)),
            ("Storage", (("storage", "Storage devices"),)),
        )
        for index, (title, fields) in enumerate(panels):
            grid.attach(self._build_system_panel(title, fields), index % 2, index // 2, 1, 1)
        page.pack_start(grid, True, True, 0)
        return scrolled(page)

    def _build_system_panel(
        self, title: str, fields: tuple[tuple[str, str], ...]
    ) -> Gtk.Widget:
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        panel.set_hexpand(True)
        panel.set_vexpand(True)
        add_class(panel, "system-panel")
        title_label = Gtk.Label(label=title, xalign=0)
        add_class(title_label, "system-panel-title")
        panel.pack_start(title_label, False, False, 0)

        values = Gtk.Grid(column_spacing=16, row_spacing=8)
        for row, (key, caption) in enumerate(fields):
            caption_label = Gtk.Label(label=caption, xalign=0, yalign=0)
            add_class(caption_label, "system-field-name")
            value_label = Gtk.Label(label="—", xalign=0, yalign=0)
            value_label.set_hexpand(True)
            value_label.set_selectable(True)
            value_label.set_line_wrap(True)
            value_label.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            add_class(value_label, "system-field-value")
            values.attach(caption_label, 0, row, 1, 1)
            values.attach(value_label, 1, row, 1, 1)
            self.system_labels[key] = value_label
        panel.pack_start(values, True, True, 0)
        return panel

    def _build_users_page(self) -> Gtk.Widget:
        page = self._page("Users", "Signed-in sessions and resources used by each account.")
        self.user_store = Gtk.ListStore(str, int, int, str, str, str)
        self.user_tree = Gtk.TreeView(model=self.user_store)
        self._text_column(self.user_tree, "User", 0, expand=True)
        self._text_column(self.user_tree, "Sessions", 1)
        self._text_column(self.user_tree, "Processes", 2)
        self._text_column(self.user_tree, "CPU", 3)
        self._text_column(self.user_tree, "Memory", 4)
        self._text_column(self.user_tree, "Terminals", 5)
        page.pack_start(scrolled(self.user_tree), True, True, 0)
        return page

    def _build_settings_page(self) -> Gtk.Widget:
        page = self._page("Settings", "Application preferences and software information.")

        identity = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        add_class(identity, "settings-hero")
        icon = Gtk.Image.new_from_icon_name(
            "io.github.systemtaskmanager.TaskManager", Gtk.IconSize.DIALOG
        )
        icon.set_pixel_size(52)
        identity.pack_start(icon, False, False, 0)
        identity_text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        app_name = Gtk.Label(label="Linux Task Manager", xalign=0)
        add_class(app_name, "settings-app-title")
        version = Gtk.Label(label=f"> linux-task-manager v{__version__}", xalign=0)
        add_class(version, "settings-version")
        description = Gtk.Label(
            label="A native GTK task and performance manager for Linux.", xalign=0
        )
        add_class(description, "settings-description")
        identity_text.pack_start(app_name, False, False, 0)
        identity_text.pack_start(version, False, False, 0)
        identity_text.pack_start(description, False, False, 0)
        identity.pack_start(identity_text, True, True, 0)
        about = Gtk.Button(label="About")
        about.connect("clicked", self._show_about)
        identity.pack_end(about, False, False, 0)
        page.pack_start(identity, False, False, 0)

        preferences = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        add_class(preferences, "settings-panel")
        preferences_title = Gtk.Label(label="Preferences", xalign=0)
        add_class(preferences_title, "settings-heading")
        preferences.pack_start(preferences_title, False, False, 0)

        self.settings_update_combo = Gtk.ComboBoxText()
        for label in ("High · every 0.5 seconds", "Normal · every second", "Low · every 3 seconds"):
            self.settings_update_combo.append_text(label)
        self.settings_update_combo.set_active(1)
        self.settings_update_combo.connect("changed", self._settings_refresh_speed_changed)
        preferences.pack_start(
            self._build_settings_row(
                "Update speed",
                "How often live process and performance values are refreshed.",
                self.settings_update_combo,
            ),
            False,
            False,
            0,
        )

        self.settings_always_on_top = Gtk.Switch()
        self.settings_always_on_top.set_active(self._always_on_top)
        self.settings_always_on_top.connect(
            "notify::active", self._settings_always_on_top_changed
        )
        preferences.pack_start(
            self._build_settings_row(
                "Always on top",
                "Keep Task Manager above other application windows.",
                self.settings_always_on_top,
            ),
            False,
            False,
            0,
        )
        page.pack_start(preferences, False, False, 0)

        actions = Gtk.Grid(column_spacing=12, row_spacing=12)
        actions.set_column_homogeneous(True)

        shortcut_panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        add_class(shortcut_panel, "settings-panel")
        shortcut_title = Gtk.Label(label="Keyboard shortcut", xalign=0)
        add_class(shortcut_title, "settings-heading")
        shortcut_description = Gtk.Label(
            label="Open or focus Task Manager with Ctrl+Shift+Esc.", xalign=0
        )
        shortcut_description.set_line_wrap(True)
        add_class(shortcut_description, "settings-description")
        self.settings_shortcut_status = Gtk.Label(
            label="Supported automatically on GNOME, Cinnamon, and Xfce.", xalign=0
        )
        self.settings_shortcut_status.set_line_wrap(True)
        add_class(self.settings_shortcut_status, "settings-description")
        shortcut_button = Gtk.Button(label="Activate Ctrl+Shift+Esc")
        shortcut_button.connect("clicked", self._install_shortcut)
        shortcut_button.set_halign(Gtk.Align.START)
        shortcut_panel.pack_start(shortcut_title, False, False, 0)
        shortcut_panel.pack_start(shortcut_description, False, False, 0)
        shortcut_panel.pack_start(self.settings_shortcut_status, False, False, 0)
        shortcut_panel.pack_end(shortcut_button, False, False, 0)
        actions.attach(shortcut_panel, 0, 0, 1, 1)

        source_panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        add_class(source_panel, "settings-panel")
        source_title = Gtk.Label(label="Source repository", xalign=0)
        add_class(source_title, "settings-heading")
        source_description = Gtk.Label(
            label="View the source code, project history, and issue tracker.", xalign=0
        )
        source_description.set_line_wrap(True)
        add_class(source_description, "settings-description")
        source_url = Gtk.Label(label=PROJECT_URL, xalign=0)
        source_url.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        source_url.set_tooltip_text(PROJECT_URL)
        add_class(source_url, "settings-link")
        source_button = Gtk.Button(label="Open repository")
        source_button.connect("clicked", self._open_project_url)
        source_button.set_halign(Gtk.Align.START)
        source_panel.pack_start(source_title, False, False, 0)
        source_panel.pack_start(source_description, False, False, 0)
        source_panel.pack_start(source_url, False, False, 0)
        source_panel.pack_end(source_button, False, False, 0)
        actions.attach(source_panel, 1, 0, 1, 1)

        page.pack_start(actions, True, True, 0)
        return scrolled(page)

    @staticmethod
    def _build_settings_row(
        title: str, description: str, control: Gtk.Widget
    ) -> Gtk.Widget:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=18)
        add_class(row, "settings-row")
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        title_label = Gtk.Label(label=title, xalign=0)
        add_class(title_label, "settings-option-title")
        description_label = Gtk.Label(label=description, xalign=0)
        description_label.set_line_wrap(True)
        add_class(description_label, "settings-description")
        text.pack_start(title_label, False, False, 0)
        text.pack_start(description_label, False, False, 0)
        row.pack_start(text, True, True, 0)
        control.set_valign(Gtk.Align.CENTER)
        row.pack_end(control, False, False, 0)
        return row

    @staticmethod
    def _text_column(
        tree: Gtk.TreeView,
        title: str,
        model_index: int,
        *,
        sort: int | None = None,
        expand: bool = False,
        minimum: int = 0,
        align: float = 0.0,
    ) -> Gtk.TreeViewColumn:
        renderer = Gtk.CellRendererText()
        renderer.set_property("xalign", align)
        renderer.set_property("ypad", 7)
        column = Gtk.TreeViewColumn(title, renderer, text=model_index)
        column.set_resizable(True)
        column.set_expand(expand)
        if minimum:
            column.set_min_width(minimum)
        column.set_sort_column_id(model_index if sort is None else sort)
        tree.append_column(column)
        return column

    @staticmethod
    def _icon_text_column(
        tree: Gtk.TreeView,
        title: str,
        icon_index: int,
        text_index: int,
        *,
        expand: bool = False,
        minimum: int = 0,
    ) -> Gtk.TreeViewColumn:
        icon = Gtk.CellRendererPixbuf()
        icon.set_property("ypad", 8)
        icon.set_property("stock-size", Gtk.IconSize.MENU)
        text = Gtk.CellRendererText()
        text.set_property("ypad", 10)
        column = Gtk.TreeViewColumn(title)
        column.pack_start(icon, False)
        column.pack_start(text, True)
        column.add_attribute(icon, "icon-name", icon_index)
        column.add_attribute(text, "text", text_index)
        column.set_sort_column_id(text_index)
        column.set_resizable(True)
        column.set_expand(expand)
        if minimum:
            column.set_min_width(minimum)
        tree.append_column(column)
        return column

    def _process_name_column(self) -> Gtk.TreeViewColumn:
        expander = Gtk.CellRendererText()
        expander.set_property("ypad", 10)
        expander.set_property("xpad", 1)
        icon = Gtk.CellRendererPixbuf()
        icon.set_property("ypad", 8)
        icon.set_property("stock-size", Gtk.IconSize.MENU)
        text = Gtk.CellRendererText()
        text.set_property("ypad", 10)
        column = Gtk.TreeViewColumn("Name")
        column.pack_start(expander, False)
        column.pack_start(icon, False)
        column.pack_start(text, True)
        column.set_cell_data_func(expander, self._style_process_expander_cell)
        column.add_attribute(icon, "icon-name", 0)
        column.add_attribute(text, "text", 1)
        column.set_cell_data_func(text, self._style_process_name_cell)
        column.set_resizable(True)
        column.set_expand(True)
        column.set_min_width(230)
        self._configure_process_sort_column(column, 1)
        self.process_tree.append_column(column)
        return column

    def _style_process_expander_cell(
        self,
        _column: Gtk.TreeViewColumn,
        renderer: Gtk.CellRendererText,
        model: Gtk.TreeModel,
        iterator: Gtk.TreeIter,
        _data: object = None,
    ) -> None:
        has_children = model.iter_has_child(iterator)
        renderer.set_property("visible", has_children)
        if not has_children:
            return
        path = model.get_path(iterator)
        renderer.set_property(
            "text", "▾" if self.process_tree.row_expanded(path) else "▸"
        )
        renderer.set_property("foreground", "#b8c8be")
        renderer.set_property("weight", Pango.Weight.BOLD)

    def _process_text_column(
        self,
        title: str,
        model_index: int,
        *,
        sort: int,
        align: float = 0.0,
        minimum: int = 0,
    ) -> Gtk.TreeViewColumn:
        renderer = Gtk.CellRendererText()
        renderer.set_property("xalign", align)
        renderer.set_property("ypad", 10)
        column = Gtk.TreeViewColumn(title, renderer, text=model_index)
        column.set_cell_data_func(renderer, self._style_process_value_cell)
        column.set_resizable(True)
        if minimum:
            column.set_min_width(minimum)
        self._configure_process_sort_column(column, sort)
        self.process_tree.append_column(column)
        return column

    def _configure_process_sort_column(
        self, column: Gtk.TreeViewColumn, sort_column: int
    ) -> None:
        column.set_clickable(True)
        column.connect("clicked", self._process_column_clicked, sort_column)
        self._process_sort_columns[sort_column] = column

    def _process_column_clicked(
        self, _column: Gtk.TreeViewColumn, sort_column: int
    ) -> None:
        if sort_column == self._process_sort_column:
            order = (
                Gtk.SortType.ASCENDING
                if self._process_sort_order == Gtk.SortType.DESCENDING
                else Gtk.SortType.DESCENDING
            )
        else:
            order = (
                Gtk.SortType.ASCENDING
                if sort_column in {1, 2}
                else Gtk.SortType.DESCENDING
            )
        if sort_column not in {1, 2}:
            self.process_store.set_sort_column_id(
                Gtk.TREE_SORTABLE_UNSORTED_SORT_COLUMN_ID,
                Gtk.SortType.ASCENDING,
            )
            self._freeze_process_sort_ranks(sort_column, order)
        self._set_process_sort(sort_column, order)

    def _set_process_sort(self, sort_column: int, order: Gtk.SortType) -> None:
        self._process_sort_column = sort_column
        self._process_sort_order = order
        self.process_store.set_sort_column_id(sort_column, order)
        for column_id, column in self._process_sort_columns.items():
            active = column_id == sort_column
            column.set_sort_indicator(active)
            if active:
                column.set_sort_order(order)

    def _freeze_process_sort_ranks(
        self, sort_column: int, order: Gtk.SortType
    ) -> None:
        """Capture the current sort order so metric refreshes cannot move rows."""
        if not hasattr(self, "process_store"):
            return
        section = self.process_store.get_iter_first()
        while section:
            section_rows = self._process_child_rows(section)
            ordered_groups = self._ordered_process_rows(
                section_rows, sort_column, order
            )
            for rank, row in enumerate(ordered_groups):
                self.process_store.set_value(row, 14, rank)
                if self.process_store.get_value(row, self.PROCESS_KIND) != "group":
                    continue
                root = self.process_store.get_value(row, self.PROCESS_OBJECT)
                members = self._process_child_rows(row)
                root_rows = [
                    member
                    for member in members
                    if self.process_store.get_value(member, self.PROCESS_OBJECT).pid
                    == root.pid
                    and self.process_store.get_value(
                        member, self.PROCESS_OBJECT
                    ).start_ticks
                    == root.start_ticks
                ]
                subprocesses = [member for member in members if member not in root_rows]
                ordered_members = root_rows + self._ordered_process_rows(
                    subprocesses, sort_column, order
                )
                for member_rank, member in enumerate(ordered_members):
                    self.process_store.set_value(member, 14, member_rank)
            section = self.process_store.iter_next(section)

    def _process_child_rows(self, parent: Gtk.TreeIter) -> list[Gtk.TreeIter]:
        rows: list[Gtk.TreeIter] = []
        child = self.process_store.iter_children(parent)
        while child:
            rows.append(child)
            child = self.process_store.iter_next(child)
        return rows

    def _ordered_process_rows(
        self,
        rows: list[Gtk.TreeIter],
        sort_column: int,
        order: Gtk.SortType,
    ) -> list[Gtk.TreeIter]:
        def key(row: Gtk.TreeIter) -> tuple[object, str, int]:
            value = self.process_store.get_value(row, sort_column)
            if isinstance(value, str):
                value = value.casefold()
            process = self.process_store.get_value(row, self.PROCESS_OBJECT)
            return value, process.name.casefold(), process.pid

        return sorted(
            rows, key=key, reverse=order == Gtk.SortType.DESCENDING
        )

    def _style_process_name_cell(
        self,
        _column: Gtk.TreeViewColumn,
        renderer: Gtk.CellRendererText,
        model: Gtk.TreeModel,
        iterator: Gtk.TreeIter,
        _data: object = None,
    ) -> None:
        process = model.get_value(iterator, self.PROCESS_OBJECT)
        is_section = process is None
        is_group = not is_section and model.iter_has_child(iterator)
        renderer.set_property(
            "weight", Pango.Weight.BOLD if is_section else (Pango.Weight.SEMIBOLD if is_group else Pango.Weight.NORMAL)
        )
        renderer.set_property("foreground-set", is_section)
        if is_section:
            renderer.set_property("foreground", "#72f5b0")

    def _style_process_value_cell(
        self,
        _column: Gtk.TreeViewColumn,
        renderer: Gtk.CellRendererText,
        model: Gtk.TreeModel,
        iterator: Gtk.TreeIter,
        _data: object = None,
    ) -> None:
        renderer.set_property("visible", model.get_value(iterator, self.PROCESS_OBJECT) is not None)

    def _process_sort_rows(
        self,
        model: Gtk.TreeModel,
        first: Gtk.TreeIter,
        second: Gtk.TreeIter,
        column: int,
    ) -> int:
        first_process = model.get_value(first, self.PROCESS_OBJECT)
        second_process = model.get_value(second, self.PROCESS_OBJECT)
        if first_process is None and second_process is None:
            first_name = model.get_value(first, 1)
            second_name = model.get_value(second, 1)
            first_rank = next((i for i, name in enumerate(SECTION_ORDER) if first_name.startswith(name)), 99)
            second_rank = next((i for i, name in enumerate(SECTION_ORDER) if second_name.startswith(name)), 99)
            result = (first_rank > second_rank) - (first_rank < second_rank)
            sort_info = model.get_sort_column_id()
            if sort_info and sort_info[-1] == Gtk.SortType.DESCENDING:
                result = -result
            return result
        if first_process is None:
            return -1
        if second_process is None:
            return 1
        parent = model.iter_parent(first)
        if (
            parent
            and model.get_value(parent, self.PROCESS_KIND) == "section"
            and column not in {1, 2}
        ):
            first_rank = model.get_value(first, 14)
            second_rank = model.get_value(second, 14)
            result = (first_rank > second_rank) - (first_rank < second_rank)
            sort_info = model.get_sort_column_id()
            if sort_info and sort_info[-1] == Gtk.SortType.DESCENDING:
                result = -result
            return result
        if parent and model.get_value(parent, self.PROCESS_KIND) == "group":
            root = model.get_value(parent, self.PROCESS_OBJECT)
            first_is_root = first_process.pid == root.pid and first_process.start_ticks == root.start_ticks
            second_is_root = second_process.pid == root.pid and second_process.start_ticks == root.start_ticks
            if first_is_root != second_is_root:
                result = -1 if first_is_root else 1
                sort_info = model.get_sort_column_id()
                if sort_info and sort_info[-1] == Gtk.SortType.DESCENDING:
                    result = -result
                return result
            if column not in {1, 2}:
                first_rank = model.get_value(first, 14)
                second_rank = model.get_value(second, 14)
                result = (first_rank > second_rank) - (first_rank < second_rank)
                sort_info = model.get_sort_column_id()
                if sort_info and sort_info[-1] == Gtk.SortType.DESCENDING:
                    result = -result
                return result
        first_value = model.get_value(first, column)
        second_value = model.get_value(second, column)
        if isinstance(first_value, str):
            first_value, second_value = first_value.casefold(), second_value.casefold()
        result = (first_value > second_value) - (first_value < second_value)
        if result == 0:
            first_key = (first_process.name.casefold(), first_process.pid)
            second_key = (second_process.name.casefold(), second_process.pid)
            result = (first_key > second_key) - (first_key < second_key)
        return result

    def _navigate(self, button: Gtk.RadioButton, name: str) -> None:
        if not button.get_active():
            return
        self.stack.set_visible_child_name(name)
        if name == "services" and not self._services_loaded:
            self._refresh_services()
        elif name == "system" and not self._system_info_loaded:
            self._load_system_info()
        elif name == "history":
            self._update_history(self._latest_history_records)
        elif name == "users":
            self._update_users(self.processes)
            self._last_users_update = time.monotonic()

    def _refresh_tick(self) -> bool:
        if time.monotonic() - self._last_request >= self._refresh_interval:
            self._request_refresh()
        return True

    def _request_refresh(self, force: bool = False) -> bool:
        if self._refresh_pending:
            return False
        self._refresh_pending = True
        self._last_request = time.monotonic()
        future = self.executor.submit(self.monitor.collect)
        future.add_done_callback(self._monitor_ready)
        return False

    def _monitor_ready(self, future: Future) -> None:
        try:
            snapshot, processes = future.result()
            GLib.idle_add(self._apply_monitor_data, snapshot, processes)
        except Exception as error:  # keep the UI alive if procfs changes mid-read
            GLib.idle_add(self._monitor_failed, str(error))

    def _monitor_failed(self, message: str) -> bool:
        self._refresh_pending = False
        self._show_message(f"System data refresh failed: {message}", Gtk.MessageType.ERROR)
        return False

    def _apply_monitor_data(
        self, snapshot: SystemSnapshot, processes: list[ProcessInfo]
    ) -> bool:
        self._refresh_pending = False
        self.snapshot = snapshot
        classified: list[ProcessInfo] = []
        for process in processes:
            _icon, known_application = self.icon_resolver.resolve(process)
            classified.append(
                replace(process, is_application=True)
                if known_application
                else process
            )
        self.processes = self.process_stabilizer.update(classified)
        self.process_groups = build_process_groups(self.processes)
        self._update_summary_cards(snapshot)
        self._update_performance(snapshot)
        self._rebuild_process_store()
        records = self.activity_history.update(
            self._history_samples(self.process_groups), snapshot.timestamp
        )
        self._latest_history_records = records
        visible_page = self.stack.get_visible_child_name()
        if visible_page == "history":
            self._update_history(records)
        if (
            visible_page == "users"
            and time.monotonic() - self._last_users_update >= 3.0
        ):
            self._update_users(self.processes)
            self._last_users_update = time.monotonic()
        return False

    def _update_summary_cards(self, snapshot: SystemSnapshot) -> None:
        temperature = (
            f"{snapshot.temperature_c:.0f} °C" if snapshot.temperature_c is not None else "No sensor"
        )
        self.summary_cpu.update_value(
            format_percent(snapshot.cpu_percent),
            left_detail=f"{snapshot.cpu_count} logical CPUs",
            right_detail=temperature,
            primary=snapshot.cpu_percent,
        )
        self.summary_memory.update_value(
            format_percent(snapshot.memory_percent),
            left_detail=f"Used {format_bytes(snapshot.memory_used)}",
            right_detail=f"Free {format_bytes(snapshot.memory_available)}",
            primary=snapshot.memory_percent,
        )
        self.summary_disk.update_value(
            format_percent(snapshot.disk_busy_percent),
            left_detail=f"Read {format_rate(snapshot.disk_read_rate)}",
            right_detail=f"Write {format_rate(snapshot.disk_write_rate)}",
            primary=snapshot.disk_busy_percent,
        )
        self.summary_network.update_value(
            format_rate(snapshot.network_receive_rate),
            left_detail=(
                f'<span foreground="#36e58a">●</span> Down '
                f"{format_rate(snapshot.network_receive_rate)}"
            ),
            right_detail=(
                f'<span foreground="#ad5cff">●</span> Up '
                f"{format_rate(snapshot.network_send_rate)}"
            ),
            primary=snapshot.network_receive_rate,
            secondary=snapshot.network_send_rate,
        )

    def _update_performance(self, snapshot: SystemSnapshot) -> None:
        self.cpu_card.update_value(
            snapshot.cpu_percent,
            left_detail=f"Load {snapshot.load_average[0]:.2f}",
            right_detail=f"{snapshot.cpu_count} logical CPUs",
        )
        self.memory_card.update_value(
            snapshot.memory_percent,
            value=f"{format_bytes(snapshot.memory_used)} / {format_bytes(snapshot.memory_total)}",
            left_detail=f"Available {format_bytes(snapshot.memory_available)}",
            right_detail=f"Cached {format_bytes(snapshot.memory_cached)}",
        )
        self.disk_card.update_value(
            snapshot.disk_busy_percent,
            left_detail=f"Read {format_rate(snapshot.disk_read_rate)}",
            right_detail=f"Write {format_rate(snapshot.disk_write_rate)}",
        )
        self.network_card.update_value(
            snapshot.network_receive_rate,
            secondary=snapshot.network_send_rate,
            value=f"↓ {format_rate(snapshot.network_receive_rate)}",
            left_detail=(
                f'<span foreground="#36e58a">●</span> Download '
                f"{format_rate(snapshot.network_receive_rate)}"
            ),
            right_detail=(
                f'<span foreground="#ad5cff">●</span> Upload '
                f"{format_rate(snapshot.network_send_rate)}"
            ),
        )
        values = {
            "Processor": snapshot.cpu_model,
            "Cores": str(snapshot.cpu_count),
            "Processes": str(snapshot.process_count),
            "Threads": str(snapshot.thread_count),
            "Uptime": format_uptime(snapshot.uptime_seconds),
            "Load average": " / ".join(f"{value:.2f}" for value in snapshot.load_average),
        }
        for key, value in values.items():
            self.performance_details[key].set_text(value)
            self.performance_details[key].set_tooltip_text(value)

    def _history_samples(self, groups: list[ProcessGroup]) -> list[HistorySample]:
        samples: list[HistorySample] = []
        for group in groups:
            root = group.root.process
            icon_name, _known = self.icon_resolver.resolve(root)
            identity = root.executable or root.command.split(" ", 1)[0] or root.name
            samples.append(
                HistorySample(
                    key=f"{root.uid}:{identity}:{root.name}",
                    name=root.name,
                    icon_name=icon_name,
                    cpu_percent=group.root.cpu_percent,
                    memory_bytes=group.root.memory_bytes,
                    process_io=tuple(
                        (
                            (process.pid, process.start_ticks),
                            process.read_bytes + process.write_bytes,
                        )
                        for process in group.root.members
                    ),
                )
            )
        return samples

    def _update_history(self, records: list[HistoryRecord]) -> None:
        if not hasattr(self, "history_store"):
            return
        for record in records:
            values = [
                record.icon_name,
                record.name,
                self._format_cpu_time(record.cpu_seconds),
                format_percent(record.average_cpu),
                format_bytes(record.peak_memory),
                format_bytes(record.disk_bytes),
                datetime.fromtimestamp(record.last_seen).strftime("%H:%M:%S"),
            ]
            iterator = self._history_row_iters.get(record.key)
            if iterator is None:
                iterator = self.history_store.append(values)
                self._history_row_iters[record.key] = iterator
            else:
                for column, value in enumerate(values):
                    self.history_store.set_value(iterator, column, value)
        total_cpu = sum(record.cpu_seconds for record in records)
        total_disk = sum(record.disk_bytes for record in records)
        self.history_groups_card.update_value(str(len(records)), "App and process groups")
        self.history_cpu_card.update_value(self._format_cpu_time(total_cpu), "Since this window opened")
        self.history_disk_card.update_value(format_bytes(total_disk), "Read and write deltas")
        self.history_session_label.set_text(
            f"Session started {datetime.fromtimestamp(self._history_started).strftime('%H:%M:%S')}"
        )

    @staticmethod
    def _format_cpu_time(seconds: float) -> str:
        if seconds < 60:
            return f"{seconds:.1f} s"
        minutes, remainder = divmod(int(seconds), 60)
        if minutes < 60:
            return f"{minutes}m {remainder}s"
        hours, minutes = divmod(minutes, 60)
        return f"{hours}h {minutes}m"

    def _clear_history(self, _button: Gtk.Button) -> None:
        self.activity_history.clear()
        self.history_store.clear()
        self._history_row_iters.clear()
        self._history_started = time.time()
        self.history_groups_card.update_value("0", "App and process groups")
        self.history_cpu_card.update_value("0.0 s", "Since this window opened")
        self.history_disk_card.update_value("0 B", "Read and write deltas")

    def _rebuild_process_store(self, force_structure: bool = False) -> None:
        if not hasattr(self, "process_store"):
            return
        selection_model, selection_iterator = self.process_tree.get_selection().get_selected()
        selected = (
            selection_model.get_value(selection_iterator, self.PROCESS_OBJECT)
            if selection_iterator
            else None
        )
        selected_kind = (
            selection_model.get_value(selection_iterator, self.PROCESS_KIND)
            if selection_iterator
            else ""
        )
        selected_key = (selected.pid, selected.start_ticks) if selected else None
        query = self.process_search.get_text().strip()
        filter_name = self.process_filter.get_active_text() or "All processes"
        groups = filter_process_groups(
            self.process_groups, filter_name, query, os.getuid()
        )
        structure = self._group_structure(groups)
        if structure == self._process_structure and self._process_row_iters:
            for group in groups:
                self._update_process_group(group)
            if query:
                self._rebuilding_process_model = True
                self.process_tree.expand_all()
                self._rebuilding_process_model = False
            return

        if (
            self._process_row_iters
            and not force_structure
            and time.monotonic() - self._last_process_structure_update < 3.0
        ):
            for group in groups:
                self._update_process_group(group)
            return

        anchor = self._process_view_anchor()
        scroll_value = self.process_scroll.get_vadjustment().get_value()
        self._rebuilding_process_model = True
        try:
            self.process_store.set_sort_column_id(
                Gtk.TREE_SORTABLE_UNSORTED_SORT_COLUMN_ID,
                Gtk.SortType.ASCENDING,
            )
            self.process_store.clear()
            self._process_row_iters.clear()
            self._process_group_iters.clear()
            self._process_section_iters.clear()
            grouped = {
                section: [group for group in groups if group.section == section]
                for section in SECTION_ORDER
            }
            for section in SECTION_ORDER:
                section_groups = grouped[section]
                if not section_groups:
                    continue
                section_iterator = self.process_store.append(
                    None,
                    [
                        "folder-symbolic",
                        f"{section} ({len(section_groups)})",
                        0,
                        "",
                        "",
                        0.0,
                        "",
                        0.0,
                        "",
                        0.0,
                        "",
                        "",
                        None,
                        "section",
                        0,
                    ],
                )
                self._process_section_iters[section] = section_iterator
                ordered_groups = sorted(
                    section_groups,
                    key=lambda group: (
                        -group.root.memory_bytes,
                        group.root.process.name.casefold(),
                        group.root.process.pid,
                    ),
                )
                for group_rank, group in enumerate(ordered_groups):
                    self._append_process_group(section_iterator, group, group_rank)

            if self._process_sort_column not in {1, 2}:
                self._freeze_process_sort_ranks(
                    self._process_sort_column, self._process_sort_order
                )
            self._set_process_sort(
                self._process_sort_column, self._process_sort_order
            )
            self._process_structure = structure
            self._last_process_structure_update = time.monotonic()
            iterator = self.process_store.get_iter_first()
            while iterator:
                self.process_tree.expand_row(self.process_store.get_path(iterator), False)
                iterator = self.process_store.iter_next(iterator)
            for key in self._expanded_process_groups:
                row = self._process_group_iters.get(key)
                if row:
                    self.process_tree.expand_row(self.process_store.get_path(row), False)
            if query:
                self.process_tree.expand_all()
            selected_rows = (
                self._process_group_iters if selected_kind == "group" else self._process_row_iters
            )
            if selected_key in selected_rows:
                row = selected_rows[selected_key]
                self.process_tree.get_selection().select_path(self.process_store.get_path(row))
        finally:
            self._rebuilding_process_model = False
        GLib.idle_add(self._restore_process_view, anchor, scroll_value)

    def _group_structure(
        self, groups: list[ProcessGroup]
    ) -> tuple[tuple[object, ...], ...]:
        result: list[tuple[object, ...]] = []
        for group in groups:
            root_key = (group.root.process.pid, group.root.process.start_ticks)
            members = group.root.members
            if len(members) > 1:
                result.append((group.section, "group", root_key))
            for process in members:
                result.append((group.section, "process", (process.pid, process.start_ticks), root_key))
        return tuple(result)

    def _append_process_group(
        self, section_iterator: Gtk.TreeIter, group: ProcessGroup, group_rank: int
    ) -> None:
        root = group.root.process
        members = group.root.members
        parent = section_iterator
        if len(members) > 1:
            parent = self.process_store.append(
                section_iterator, self._process_group_values(group, group_rank)
            )
            self._process_group_iters[(root.pid, root.start_ticks)] = parent
        application_name = self.icon_resolver.display_name(root)
        ordered_members = [root]
        ordered_members.extend(
            sorted(
                (process for process in members if process.pid != root.pid),
                key=lambda process: (-process.rss_bytes, process.name.casefold(), process.pid),
            )
        )
        for rank, process in enumerate(ordered_members):
            row_rank = rank if len(members) > 1 else group_rank
            iterator = self.process_store.append(
                parent,
                self._process_member_values(process, root, application_name, row_rank),
            )
            self._process_row_iters[(process.pid, process.start_ticks)] = iterator

    def _update_process_group(self, group: ProcessGroup) -> None:
        root = group.root.process
        group_iterator = self._process_group_iters.get((root.pid, root.start_ticks))
        if group_iterator:
            self._update_process_metrics(
                group_iterator,
                root,
                group.root.cpu_percent,
                group.root.memory_bytes,
                group.root.io_rate,
                f"{len(group.root.members)} processes",
            )
        for process in group.root.members:
            iterator = self._process_row_iters.get((process.pid, process.start_ticks))
            if iterator:
                self._update_process_metrics(
                    iterator,
                    process,
                    process.cpu_percent,
                    process.rss_bytes,
                    process.io_rate,
                    process.status,
                )

    def _update_process_metrics(
        self,
        iterator: Gtk.TreeIter,
        process: ProcessInfo,
        cpu_percent: float,
        memory_bytes: int,
        io_rate: float,
        status: str,
    ) -> None:
        values = (
            (4, format_percent(cpu_percent)),
            (5, cpu_percent),
            (6, format_bytes(memory_bytes)),
            (7, float(memory_bytes)),
            (8, format_rate(io_rate)),
            (9, io_rate),
            (10, status),
            (12, process),
        )
        for column, value in values:
            if self.process_store.get_value(iterator, column) != value:
                self.process_store.set_value(iterator, column, value)

    def _set_process_row(self, iterator: Gtk.TreeIter, values: list[object]) -> None:
        for column, value in enumerate(values):
            if self.process_store.get_value(iterator, column) != value:
                self.process_store.set_value(iterator, column, value)

    def _process_group_values(self, group: ProcessGroup, rank: int) -> list[object]:
        root = group.root.process
        count = len(group.root.members)
        icon_name, _known = self.icon_resolver.resolve(root)
        display_name = self.icon_resolver.display_name(root) or root.name
        return [
            icon_name,
            f"{display_name} ({count})",
            root.pid,
            root.username,
            format_percent(group.root.cpu_percent),
            group.root.cpu_percent,
            format_bytes(group.root.memory_bytes),
            float(group.root.memory_bytes),
            format_rate(group.root.io_rate),
            group.root.io_rate,
            f"{count} processes",
            ellipsize_middle(root.command, 180),
            root,
            "group",
            rank,
        ]

    def _process_member_values(
        self,
        process: ProcessInfo,
        root: ProcessInfo,
        application_name: str | None,
        rank: int,
    ) -> list[object]:
        icon_name, _known = self.icon_resolver.resolve(process)
        return [
            icon_name,
            process_display_name(process, root, application_name),
            process.pid,
            process.username,
            format_percent(process.cpu_percent),
            process.cpu_percent,
            format_bytes(process.rss_bytes),
            float(process.rss_bytes),
            format_rate(process.io_rate),
            process.io_rate,
            process.status,
            ellipsize_middle(process.command, 180),
            process,
            "process",
            rank,
        ]

    def _process_row_expanded(
        self, _tree: Gtk.TreeView, iterator: Gtk.TreeIter, _path: Gtk.TreePath
    ) -> None:
        self.process_tree.queue_draw()
        if self._rebuilding_process_model:
            return
        if self.process_store.get_value(iterator, self.PROCESS_KIND) == "group":
            process = self.process_store.get_value(iterator, self.PROCESS_OBJECT)
            self._expanded_process_groups.add((process.pid, process.start_ticks))

    def _process_row_collapsed(
        self, _tree: Gtk.TreeView, iterator: Gtk.TreeIter, _path: Gtk.TreePath
    ) -> None:
        self.process_tree.queue_draw()
        if self._rebuilding_process_model:
            return
        if self.process_store.get_value(iterator, self.PROCESS_KIND) == "group":
            process = self.process_store.get_value(iterator, self.PROCESS_OBJECT)
            self._expanded_process_groups.discard((process.pid, process.start_ticks))

    def _process_view_anchor(self) -> tuple[str, object] | None:
        visible = self.process_tree.get_visible_range()
        if not visible:
            return None
        paths = [item for item in visible if isinstance(item, Gtk.TreePath)]
        if not paths:
            return None
        iterator = self.process_store.get_iter(paths[0])
        kind = self.process_store.get_value(iterator, self.PROCESS_KIND)
        if kind == "section":
            label = self.process_store.get_value(iterator, 1)
            section = next((name for name in SECTION_ORDER if label.startswith(name)), label)
            return kind, section
        process = self.process_store.get_value(iterator, self.PROCESS_OBJECT)
        return kind, (process.pid, process.start_ticks)

    def _restore_process_view(
        self, anchor: tuple[str, object] | None, scroll_value: float
    ) -> bool:
        iterator = None
        if anchor:
            kind, key = anchor
            if kind == "section":
                iterator = self._process_section_iters.get(str(key))
            elif kind == "group":
                iterator = self._process_group_iters.get(key)
            elif kind == "process":
                iterator = self._process_row_iters.get(key)
        if iterator:
            self.process_tree.scroll_to_cell(
                self.process_store.get_path(iterator), None, True, 0.0, 0.0
            )
        else:
            adjustment = self.process_scroll.get_vadjustment()
            maximum = max(adjustment.get_lower(), adjustment.get_upper() - adjustment.get_page_size())
            adjustment.set_value(min(scroll_value, maximum))
        return False

    def _selected_process(self) -> ProcessInfo | None:
        if not hasattr(self, "process_tree"):
            return None
        model, iterator = self.process_tree.get_selection().get_selected()
        if iterator is None:
            return None
        return model.get_value(iterator, self.PROCESS_OBJECT)

    def _process_selection_changed(self, selection: Gtk.TreeSelection) -> None:
        has_selection = self._selected_process() is not None
        self.end_button.set_sensitive(has_selection)

    def _process_action(self, action: str, confirm: bool = True) -> None:
        process = self._selected_process()
        if not process:
            self._show_message("Select a process first.", Gtk.MessageType.INFO)
            return
        labels = {
            "terminate": ("End task", "Ask this process to close?"),
            "kill": ("Force kill", "Forcefully end this process? Unsaved work will be lost."),
        }
        if confirm and action in labels:
            label, question = labels[action]
            if not self._confirm(
                f"{label} {process.name}?",
                f"{question}\n\nPID {process.pid} • {process.username}",
                label,
            ):
                return
        if action == "toggle_suspend":
            action = "resume" if process.status == "Stopped" else "suspend"
        callback = getattr(self.controller, action)
        future = self.executor.submit(callback, process)
        future.add_done_callback(self._action_ready)

    def _set_process_priority(self, nice: int) -> None:
        process = self._selected_process()
        if not process:
            self._show_message("Select a process first.", Gtk.MessageType.INFO)
            return
        future = self.executor.submit(self.controller.set_priority, process, nice)
        future.add_done_callback(self._action_ready)

    def _action_ready(self, future: Future) -> None:
        try:
            result = future.result()
        except Exception as error:
            result = ActionResult(False, str(error))
        GLib.idle_add(self._apply_action_result, result)

    def _apply_action_result(self, result: ActionResult) -> bool:
        self._show_message(
            result.message, Gtk.MessageType.INFO if result.ok else Gtk.MessageType.ERROR
        )
        self._request_refresh(True)
        return False

    def _show_process_details(self) -> None:
        process = self._selected_process()
        if not process:
            self._show_message("Select a process first.", Gtk.MessageType.INFO)
            return
        dialog = Gtk.Dialog(
            title=f"{process.name} — Process details",
            transient_for=self,
            modal=True,
            destroy_with_parent=True,
        )
        dialog.add_button("Copy command", 1)
        if process.executable:
            dialog.add_button("Open location", 2)
        dialog.add_button("Close", Gtk.ResponseType.CLOSE)
        dialog.set_default_size(620, 430)
        grid = Gtk.Grid(column_spacing=18, row_spacing=9)
        grid.set_border_width(18)
        group = next(
            (
                item
                for item in self.process_groups
                if any(
                    member.pid == process.pid and member.start_ticks == process.start_ticks
                    for member in item.root.members
                )
            ),
            None,
        )
        root = group.root.process if group else process
        application_name = self.icon_resolver.display_name(root)
        display_name = process_display_name(process, root, application_name)
        details = (
            ("Display name", display_name),
            ("Process name", process.name),
            ("Application group", application_name or root.name),
            ("PID", str(process.pid)),
            ("Parent PID", str(process.ppid)),
            ("Session ID", str(process.session_id)),
            ("User", f"{process.username} ({process.uid})"),
            ("Status", process.status),
            ("CPU", format_percent(process.cpu_percent)),
            ("Memory", f"{format_bytes(process.rss_bytes)} ({format_percent(process.memory_percent)})"),
            ("Disk totals", f"Read {format_bytes(process.read_bytes)} • Write {format_bytes(process.write_bytes)}"),
            ("Threads", str(process.threads)),
            ("Priority (nice)", str(process.nice)),
            ("Executable", process.executable or "Not available"),
            ("Working directory", process.cwd or "Not available"),
            ("Command", process.command),
        )
        for row, (label, value) in enumerate(details):
            name = Gtk.Label(label=label, xalign=0, yalign=0)
            add_class(name, "metric-detail")
            content = Gtk.Label(label=value, xalign=0, yalign=0)
            content.set_selectable(True)
            content.set_line_wrap(True)
            content.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            content.set_max_width_chars(70)
            grid.attach(name, 0, row, 1, 1)
            grid.attach(content, 1, row, 1, 1)
        dialog.get_content_area().add(scrolled(grid))
        dialog.show_all()
        response = dialog.run()
        if response == 1:
            Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(process.command, -1)
        elif response == 2:
            self._process_action("open_location", confirm=False)
        dialog.destroy()

    def _process_context_event(self, tree: Gtk.TreeView, event: Gdk.EventButton) -> bool:
        if event.button == 1:
            hit = tree.get_path_at_pos(int(event.x), int(event.y))
            if hit and hit[1] == self.process_name_column and hit[2] <= 28:
                iterator = self.process_store.get_iter(hit[0])
                if self.process_store.iter_has_child(iterator):
                    if tree.row_expanded(hit[0]):
                        tree.collapse_row(hit[0])
                    else:
                        tree.expand_row(hit[0], False)
                    return True
            return False
        if event.button != 3:
            return False
        hit = tree.get_path_at_pos(int(event.x), int(event.y))
        if hit:
            tree.get_selection().select_path(hit[0])
            self.process_context_menu.popup_at_pointer(event)
            return True
        return False

    def _process_key_event(self, _tree: Gtk.TreeView, event: Gdk.EventKey) -> bool:
        if event.keyval == Gdk.KEY_Delete:
            self._process_action("kill" if event.state & Gdk.ModifierType.SHIFT_MASK else "terminate")
            return True
        return False

    def _load_startup_entries(self) -> None:
        if not hasattr(self, "startup_store"):
            return
        query = self.startup_search.get_text().strip().casefold()
        self.startup_store.clear()
        for entry in self.startup_manager.list_entries():
            if query and query not in f"{entry.name} {entry.command} {entry.description}".casefold():
                continue
            self.startup_store.append(
                [
                    entry.name,
                    "Enabled" if entry.enabled else "Disabled",
                    entry.command,
                    entry.scope,
                    entry.source,
                    entry,
                ]
            )

    def _selected_startup(self) -> StartupEntry | None:
        model, iterator = self.startup_tree.get_selection().get_selected()
        return model.get_value(iterator, self.STARTUP_OBJECT) if iterator else None

    def _startup_selection_changed(self, _selection: Gtk.TreeSelection) -> None:
        entry = self._selected_startup()
        self.startup_enable_button.set_sensitive(bool(entry and not entry.enabled))
        self.startup_disable_button.set_sensitive(bool(entry and entry.enabled))

    def _set_startup_enabled(self, enabled: bool) -> None:
        entry = self._selected_startup()
        if not entry:
            return
        result = self.startup_manager.set_enabled(entry, enabled)
        self._show_message(result.message, Gtk.MessageType.INFO if result.ok else Gtk.MessageType.ERROR)
        self._load_startup_entries()

    def _load_system_info(self, force: bool = False) -> None:
        if self._system_info_pending or (self._system_info_loaded and not force):
            return
        self._system_info_pending = True
        self.system_status.set_text("Detecting hardware and operating system details…")
        future = self.executor.submit(collect_system_info)
        future.add_done_callback(self._system_info_ready)

    def _system_info_ready(self, future: Future) -> None:
        try:
            info = future.result()
            GLib.idle_add(self._apply_system_info, info)
        except Exception as error:
            GLib.idle_add(self._system_info_failed, str(error))

    def _apply_system_info(self, info: SystemInfo) -> bool:
        self._system_info_pending = False
        self._system_info_loaded = True
        self.system_hostname.set_text(info.hostname)
        self.system_hostname.set_tooltip_text(info.hostname)
        values = {
            "manufacturer": info.manufacturer,
            "model": info.model,
            "firmware": info.firmware,
            "virtualization": info.virtualization,
            "os_name": info.os_name,
            "kernel": info.kernel,
            "architecture": info.architecture,
            "desktop": info.desktop,
            "session_type": info.session_type,
            "cpu_model": info.cpu_model,
            "physical_cores": str(info.physical_cores),
            "logical_cores": str(info.logical_cores),
            "max_frequency": info.max_frequency,
            "graphics": "\n".join(info.graphics),
            "memory": info.memory,
            "swap": info.swap,
            "storage": "\n".join(info.storage),
        }
        for key, value in values.items():
            label = self.system_labels[key]
            label.set_text(value)
            label.set_tooltip_text(value)
        self.system_status.set_text(
            f"Detected from Linux system interfaces · Updated {datetime.now().strftime('%H:%M:%S')}"
        )
        return False

    def _system_info_failed(self, message: str) -> bool:
        self._system_info_pending = False
        self.system_status.set_text("System information could not be detected.")
        self._show_message(f"Could not load system information: {message}", Gtk.MessageType.ERROR)
        return False

    def _refresh_services(self) -> None:
        if self._services_pending:
            return
        self._services_pending = True
        future = self.executor.submit(self.service_manager.list_services)
        future.add_done_callback(self._services_ready)

    def _services_ready(self, future: Future) -> None:
        try:
            services = future.result()
            GLib.idle_add(self._apply_services, services)
        except Exception as error:
            GLib.idle_add(self._services_failed, str(error))

    def _apply_services(self, services: list[ServiceInfo]) -> bool:
        self._services_pending = False
        self._services_loaded = True
        self.services = services
        self._rebuild_service_store()
        return False

    def _services_failed(self, message: str) -> bool:
        self._services_pending = False
        self._show_message(f"Could not load services: {message}", Gtk.MessageType.ERROR)
        return False

    def _rebuild_service_store(self) -> None:
        if not hasattr(self, "service_store"):
            return
        query = self.service_search.get_text().strip().casefold()
        self.service_store.clear()
        for service in self.services:
            if query and query not in f"{service.name} {service.description}".casefold():
                continue
            self.service_store.append(
                [
                    service.name,
                    service.description,
                    service.active_state.title(),
                    service.sub_state,
                    service.enabled_state,
                    service,
                ]
            )

    def _selected_service(self) -> ServiceInfo | None:
        model, iterator = self.service_tree.get_selection().get_selected()
        return model.get_value(iterator, self.SERVICE_OBJECT) if iterator else None

    def _service_selection_changed(self, _selection: Gtk.TreeSelection) -> None:
        service = self._selected_service()
        self.service_start_button.set_sensitive(bool(service and service.active_state != "active"))
        self.service_stop_button.set_sensitive(bool(service and service.active_state == "active"))

    def _service_action(self, action: str) -> None:
        service = self._selected_service()
        if not service:
            return
        if not self._confirm(
            f"{action.title()} {service.name}?",
            "System services can affect running applications and hardware. "
            "Administrator authorization may be requested.",
            action.title(),
        ):
            return
        future = self.executor.submit(self.service_manager.perform, service, action)
        future.add_done_callback(self._service_action_ready)

    def _service_action_ready(self, future: Future) -> None:
        try:
            result = future.result()
        except Exception as error:
            result = ActionResult(False, str(error))
        GLib.idle_add(self._apply_service_result, result)

    def _apply_service_result(self, result: ActionResult) -> bool:
        self._show_message(result.message, Gtk.MessageType.INFO if result.ok else Gtk.MessageType.ERROR)
        self._refresh_services()
        return False

    def _update_users(self, processes: list[ProcessInfo]) -> None:
        self.user_store.clear()
        for user in build_user_summary(processes):
            self.user_store.append(
                [
                    user.username,
                    user.sessions,
                    user.process_count,
                    format_percent(user.cpu_percent),
                    format_bytes(user.memory_bytes),
                    ", ".join(user.terminals) or "—",
                ]
            )

    def _set_refresh_speed(self, item: Gtk.RadioMenuItem, seconds: float) -> None:
        if item.get_active():
            self._refresh_interval = seconds
            if hasattr(self, "settings_update_combo"):
                index = {0.5: 0, 1.0: 1, 3.0: 2}[seconds]
                if self.settings_update_combo.get_active() != index:
                    self.settings_update_combo.set_active(index)

    def _settings_refresh_speed_changed(self, combo: Gtk.ComboBoxText) -> None:
        active = combo.get_active()
        if active < 0:
            return
        seconds = (0.5, 1.0, 3.0)[active]
        item = self._speed_menu_items[seconds]
        if not item.get_active():
            item.set_active(True)
        else:
            self._refresh_interval = seconds

    def _settings_always_on_top_changed(
        self, switch: Gtk.Switch, _parameter: object
    ) -> None:
        self._set_always_on_top(switch.get_active())

    def _set_always_on_top(self, active: bool) -> None:
        self._always_on_top = active
        self.set_keep_above(active)
        if self.always_on_top_menu_item.get_active() != active:
            self.always_on_top_menu_item.set_active(active)
        if (
            hasattr(self, "settings_always_on_top")
            and self.settings_always_on_top.get_active() != active
        ):
            self.settings_always_on_top.set_active(active)

    def _install_shortcut(self, _item: Gtk.Widget) -> None:
        from .shortcut import install_shortcut

        ok, message = install_shortcut(force=True)
        if hasattr(self, "settings_shortcut_status"):
            self.settings_shortcut_status.set_text(message)
        self._show_message(message, Gtk.MessageType.INFO if ok else Gtk.MessageType.WARNING)

    def _open_project_url(self, _button: Gtk.Button) -> None:
        try:
            Gio.AppInfo.launch_default_for_uri(PROJECT_URL, None)
        except GLib.Error as error:
            self._show_message(
                f"Could not open the repository: {error.message}", Gtk.MessageType.ERROR
            )

    def _show_about(self, _item: Gtk.Widget) -> None:

        dialog = Gtk.AboutDialog(transient_for=self, modal=True)
        dialog.set_program_name("Linux Task Manager")
        dialog.set_version(__version__)
        dialog.set_comments(
            "A native task and performance manager for Ubuntu and Debian.\n"
            "System data comes directly from Linux procfs and systemd."
        )
        dialog.set_logo_icon_name("io.github.systemtaskmanager.TaskManager")
        dialog.set_license_type(Gtk.License.MIT_X11)
        dialog.set_website(PROJECT_URL)
        dialog.set_website_label("Source repository")
        dialog.run()
        dialog.destroy()

    def _confirm(self, title: str, detail: str, action_label: str) -> bool:
        dialog = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            destroy_with_parent=True,
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.CANCEL,
            text=title,
        )
        dialog.format_secondary_text(detail)
        dialog.add_button(action_label, Gtk.ResponseType.OK)
        response = dialog.run()
        dialog.destroy()
        return response == Gtk.ResponseType.OK

    def _show_message(self, message: str, message_type: Gtk.MessageType) -> None:
        self.info_bar.set_message_type(message_type)
        self.info_label.set_text(message)
        self.info_bar.show_all()
        if self._message_timer:
            GLib.source_remove(self._message_timer)
        self._message_timer = GLib.timeout_add_seconds(7, self._hide_message)

    def _hide_message(self) -> bool:
        self.info_bar.hide()
        self._message_timer = None
        return False

    def _on_window_key_press(self, _window: Gtk.Window, event: Gdk.EventKey) -> bool:
        if event.keyval == Gdk.KEY_Escape and self.process_search.has_focus():
            self.process_search.set_text("")
            return True
        if event.state & Gdk.ModifierType.CONTROL_MASK and event.keyval in (Gdk.KEY_f, Gdk.KEY_F):
            visible = self.stack.get_visible_child_name()
            search = {
                "processes": self.process_search,
                "startup": self.startup_search,
                "services": self.service_search,
            }.get(visible)
            if search:
                search.grab_focus()
                return True
        return False

    def _on_destroy(self, _window: Gtk.Window) -> None:
        self.executor.shutdown(wait=False, cancel_futures=True)
