from __future__ import annotations

from collections import deque

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Pango

from .formatting import format_percent


def add_class(widget: Gtk.Widget, name: str) -> Gtk.Widget:
    widget.get_style_context().add_class(name)
    return widget


class MetricCard(Gtk.Box):
    def __init__(
        self,
        title: str,
        accent: str = "blue",
        *,
        show_graph: bool = False,
        graph_maximum: float | None = 100.0,
        primary_color: tuple[float, float, float] = (1.0, 0.30, 0.43),
        secondary_color: tuple[float, float, float] = (0.67, 0.36, 1.0),
    ) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.show_graph = show_graph
        add_class(self, "metric-card")
        add_class(self, f"accent-{accent}")
        self.set_hexpand(True)
        self.set_size_request(-1, 118)
        title_label = Gtk.Label(label=title, xalign=0)
        add_class(title_label, "metric-title")
        self.value_label = Gtk.Label(label="—", xalign=1 if show_graph else 0)
        add_class(self.value_label, "metric-value")
        if show_graph:
            self.graph = HistoryGraph(
                graph_maximum,
                points=60,
                primary_color=primary_color,
                secondary_color=secondary_color,
                compact=True,
            )
            self.graph.set_size_request(78, 30)
            metric_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            self.value_label.set_xalign(0)
            metric_row.pack_start(self.value_label, True, True, 0)
            metric_row.pack_end(self.graph, False, False, 0)
            detail_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, homogeneous=True)
            add_class(detail_row, "metric-graph-details")
            self.left_detail_label = Gtk.Label(label="", xalign=0)
            self.left_detail_label.set_ellipsize(Pango.EllipsizeMode.END)
            add_class(self.left_detail_label, "metric-detail")
            right_half = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            separator = Gtk.Label(label="|")
            add_class(separator, "graph-detail-separator")
            self.right_detail_label = Gtk.Label(label="", xalign=0)
            self.right_detail_label.set_ellipsize(Pango.EllipsizeMode.END)
            add_class(self.right_detail_label, "metric-detail")
            right_half.pack_start(separator, False, False, 0)
            right_half.pack_start(self.right_detail_label, True, True, 0)
            detail_row.pack_start(self.left_detail_label, True, True, 0)
            detail_row.pack_start(right_half, True, True, 0)
            self.pack_start(title_label, False, False, 0)
            self.pack_start(metric_row, True, True, 0)
            self.pack_start(detail_row, False, False, 0)
        else:
            self.detail_label = Gtk.Label(label="", xalign=0)
            self.detail_label.set_ellipsize(Pango.EllipsizeMode.END)
            self.detail_label.set_max_width_chars(28)
            add_class(self.detail_label, "metric-detail")
            self.pack_start(title_label, False, False, 0)
            self.pack_start(self.value_label, False, False, 0)
            self.pack_start(self.detail_label, False, False, 0)

    def update_value(
        self,
        value: str,
        detail: str = "",
        *,
        left_detail: str = "",
        right_detail: str = "",
        primary: float | None = None,
        secondary: float | None = None,
    ) -> None:
        self.value_label.set_text(value)
        if self.show_graph:
            self.left_detail_label.set_markup(left_detail or detail)
            self.right_detail_label.set_markup(right_detail)
            if primary is not None:
                self.graph.push(primary, secondary)
        else:
            self.detail_label.set_text(detail)


class HistoryGraph(Gtk.DrawingArea):
    def __init__(
        self,
        maximum: float | None = 100.0,
        points: int = 90,
        primary_color: tuple[float, float, float] = (1.0, 0.30, 0.43),
        secondary_color: tuple[float, float, float] = (0.67, 0.36, 1.0),
        compact: bool = False,
    ) -> None:
        super().__init__()
        self.maximum = maximum
        self.primary_color = primary_color
        self.secondary_color = secondary_color
        self.compact = compact
        self.primary: deque[float] = deque([0.0] * points, maxlen=points)
        self.secondary: deque[float] = deque([0.0] * points, maxlen=points)
        self.has_secondary = False
        self.set_size_request(100 if compact else 260, 52 if compact else 150)
        self.connect("draw", self._draw)

    def push(self, primary: float, secondary: float | None = None) -> None:
        self.primary.append(max(0.0, primary))
        if secondary is not None:
            self.secondary.append(max(0.0, secondary))
            self.has_secondary = True
        else:
            self.secondary.append(0.0)
        self.queue_draw()

    def _draw(self, _widget: Gtk.Widget, context: object) -> bool:
        width = self.get_allocated_width()
        height = self.get_allocated_height()
        if width <= 1 or height <= 1:
            return False

        context.set_source_rgb(0.025, 0.035, 0.065)
        context.paint()
        context.set_line_width(1)
        context.set_source_rgba(0.45, 0.52, 0.68, 0.16)
        horizontal_lines = 2 if self.compact else 4
        vertical_lines = 3 if self.compact else 6
        for index in range(1, horizontal_lines):
            y = height * index / horizontal_lines
            context.move_to(0, y)
            context.line_to(width, y)
        for index in range(1, vertical_lines):
            x = width * index / vertical_lines
            context.move_to(x, 0)
            context.line_to(x, height)
        context.stroke()

        values = list(self.primary)
        secondary = list(self.secondary)
        ceiling = self.maximum or max([1.0, *values, *secondary]) * 1.15
        self._path(context, values, ceiling, width, height, self.primary_color, True, self.compact)
        if self.has_secondary:
            self._path(context, secondary, ceiling, width, height, self.secondary_color, False, self.compact)
        return False

    @staticmethod
    def _path(
        context: object,
        values: list[float],
        ceiling: float,
        width: int,
        height: int,
        color: tuple[float, float, float],
        fill: bool,
        compact: bool,
    ) -> None:
        if len(values) < 2 or ceiling <= 0:
            return
        points = [
            (
                index * width / (len(values) - 1),
                height - min(1.0, value / ceiling) * (height - 4) - 2,
            )
            for index, value in enumerate(values)
        ]
        context.move_to(*points[0])
        for point in points[1:]:
            context.line_to(*point)
        if fill:
            context.line_to(width, height)
            context.line_to(0, height)
            context.close_path()
            context.set_source_rgba(*color, 0.14)
            context.fill()
            context.move_to(*points[0])
            for point in points[1:]:
                context.line_to(*point)
        # Layered strokes create a restrained neon glow on the dark plot.
        context.set_source_rgba(*color, 0.12)
        context.set_line_width(5 if compact else 8)
        context.stroke_preserve()
        context.set_source_rgba(*color, 0.28)
        context.set_line_width(3 if compact else 4)
        context.stroke_preserve()
        context.set_source_rgba(*color, 0.95)
        context.set_line_width(1.5 if compact else 2)
        context.stroke()
        context.arc(points[-1][0], points[-1][1], 2.2 if compact else 3.2, 0, 6.283)
        context.set_source_rgba(*color, 1.0)
        context.fill()


class PerformanceCard(Gtk.Box):
    def __init__(
        self,
        title: str,
        maximum: float | None = 100.0,
        primary_color: tuple[float, float, float] = (1.0, 0.30, 0.43),
        secondary_color: tuple[float, float, float] = (0.67, 0.36, 1.0),
    ) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        add_class(self, "performance-card")
        self.set_hexpand(True)
        self.set_vexpand(True)
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        title_label = Gtk.Label(label=title, xalign=0)
        add_class(title_label, "performance-title")
        self.value_label = Gtk.Label(label="—", xalign=1)
        add_class(self.value_label, "performance-value")
        header.pack_start(title_label, True, True, 0)
        header.pack_end(self.value_label, False, False, 0)
        self.graph = HistoryGraph(maximum, primary_color=primary_color, secondary_color=secondary_color)
        detail_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, homogeneous=True)
        add_class(detail_row, "graph-details")
        self.left_detail_label = Gtk.Label(label="", xalign=0)
        self.left_detail_label.set_ellipsize(Pango.EllipsizeMode.END)
        add_class(self.left_detail_label, "metric-detail")
        right_half = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        separator = Gtk.Label(label="|")
        add_class(separator, "graph-detail-separator")
        self.right_detail_label = Gtk.Label(label="", xalign=0)
        self.right_detail_label.set_ellipsize(Pango.EllipsizeMode.END)
        add_class(self.right_detail_label, "metric-detail")
        right_half.pack_start(separator, False, False, 0)
        right_half.pack_start(self.right_detail_label, True, True, 0)
        detail_row.pack_start(self.left_detail_label, True, True, 0)
        detail_row.pack_start(right_half, True, True, 0)
        self.pack_start(header, False, False, 0)
        self.pack_start(self.graph, True, True, 0)
        self.pack_start(detail_row, False, False, 0)

    def update_value(
        self,
        primary: float,
        value: str | None = None,
        left_detail: str = "",
        right_detail: str = "",
        secondary: float | None = None,
    ) -> None:
        self.value_label.set_text(value if value is not None else format_percent(primary))
        self.left_detail_label.set_markup(left_detail)
        self.right_detail_label.set_markup(right_detail)
        self.graph.push(primary, secondary)


def scrolled(widget: Gtk.Widget) -> Gtk.ScrolledWindow:
    container = Gtk.ScrolledWindow()
    container.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
    container.add(widget)
    return container
