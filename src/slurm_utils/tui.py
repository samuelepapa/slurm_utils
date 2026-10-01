"""Interactive terminal browser for the cluster resource report."""

import curses
import locale
from collections import Counter

from slurm_utils.resources import classify, format_memory, group_nodes

BUCKETS = ("free", "partial", "full", "unavailable")
BUCKET_RANK = {name: index for index, name in enumerate(BUCKETS)}
BUCKET_LABEL = {"free": "free", "partial": "partial", "full": "full", "unavailable": "down"}
FILTERS = {"a": None, "f": "free", "p": "partial", "u": "full", "d": "unavailable"}

GROUPS_HELP = "↑↓ move · → open · / search · r refresh · q quit"
NODES_HELP = "↑↓ move · → details · ← back · a/f/p/u/d filter · / search · r refresh · q quit"
DETAIL_HELP = "← or esc back · q quit"

COLORS = {
    "free": 1,
    "partial": 2,
    "full": 3,
    "unavailable": 4,
    "header": 5,
    "dim": 6,
}


def bar(free, total, width=10):
    if total <= 0:
        return " " * width
    filled = int(round(width * free / float(total)))
    filled = max(0, min(width, filled))
    return "█" * filled + "░" * (width - filled)


def percent(free, total):
    return 0 if total <= 0 else int(round(100.0 * free / total))


def summarize(nodes):
    usable = [node for node in nodes if node["available"]]
    return {
        "nodes": len(nodes),
        "usable": len(usable),
        "counts": Counter(classify(node) for node in nodes),
        "gpu_free": sum(n["gpu_total"] - n["gpu_alloc"] for n in usable),
        "gpu_total": sum(n["gpu_total"] for n in usable),
        "cpu_free": sum(n["cpu_total"] - n["cpu_alloc"] for n in usable),
        "cpu_total": sum(n["cpu_total"] for n in usable),
        "mem_free": sum(n["mem_total"] - n["mem_alloc"] for n in usable),
        "mem_total": sum(n["mem_total"] for n in usable),
    }


def group_label(key):
    gpu_type, gpu_total, _, _, _ = key
    return f"{gpu_total}x {gpu_type or 'gpu'}" if gpu_total else "CPU only"


def group_row(key, nodes):
    """One line summarizing a hardware group, as (text, colour kind)."""
    _, gpu_total, cpu_total, mem_total, partitions = key
    stats = summarize(nodes)
    counts = stats["counts"]

    if stats["gpu_total"]:
        gpus = f"{stats['gpu_free']}/{stats['gpu_total']}"
        gpu_cell = f"GPU {gpus:>11} {bar(stats['gpu_free'], stats['gpu_total'])} {percent(stats['gpu_free'], stats['gpu_total']):>3}%"
    else:
        gpu_cell = " " * 31

    cpus = f"{stats['cpu_free']}/{stats['cpu_total']}"
    cpu_cell = f"CPU {cpus:>13} {percent(stats['cpu_free'], stats['cpu_total']):>3}%"
    memory = f"{format_memory(stats['mem_free'])}/{format_memory(stats['mem_total'])}"
    mem_cell = f"RAM {memory:>13} {percent(stats['mem_free'], stats['mem_total']):>3}%"

    tally = "  ".join(
        f"{counts[name]} {BUCKET_LABEL[name]}" for name in BUCKETS if counts[name]
    )
    text = (
        f"{group_label(key):<12}  {gpu_cell}  {cpu_cell}  {mem_cell}  "
        f"{stats['nodes']:>4} nodes  {tally}"
    )
    detail = (
        f"{cpu_total} CPU, {format_memory(mem_total)} RAM per node"
        f"  ·  partitions: {','.join(partitions) or 'none'}"
    )
    kind = "free" if stats["gpu_free"] or stats["cpu_free"] else "full"
    return text, detail, kind


def sort_nodes(nodes):
    return sorted(
        nodes,
        key=lambda node: (
            BUCKET_RANK[classify(node)],
            -(node["gpu_total"] - node["gpu_alloc"]),
            -(node["cpu_total"] - node["cpu_alloc"]),
            node["name"],
        ),
    )


def filter_nodes(nodes, bucket=None, search=""):
    selected = nodes
    if bucket:
        selected = [node for node in selected if classify(node) == bucket]
    if search:
        needle = search.lower()
        selected = [node for node in selected if needle in node["name"].lower()]
    return selected


def node_reason(node):
    reason = node["reason"]
    return "" if not reason or reason == "(null)" else reason


def node_row(node, show_gpu):
    kind = classify(node)
    cells = [f"{node['name']:<30.30}", f"{BUCKET_LABEL[kind]:<8}"]

    if kind == "unavailable":
        # Idle resources on a drained node are not really free, so show why it is out instead.
        cells.append("+".join(node["states"]))
        reason = node_reason(node)
        if reason:
            cells.append(f"· {reason}")
        return "  ".join(cells), kind

    if show_gpu:
        free_gpu = node["gpu_total"] - node["gpu_alloc"]
        cells.append(f"{free_gpu}/{node['gpu_total']} GPU".rjust(10))
        cells.append(bar(free_gpu, node["gpu_total"], 8))

    free_cpu = node["cpu_total"] - node["cpu_alloc"]
    cells.append(f"{free_cpu}/{node['cpu_total']} CPU".rjust(13))
    cells.append(bar(free_cpu, node["cpu_total"], 8))

    free_mem = node["mem_total"] - node["mem_alloc"]
    cells.append(
        f"{format_memory(free_mem)}/{format_memory(node['mem_total'])} RAM".rjust(16)
    )
    cells.append(bar(free_mem, node["mem_total"], 8))
    return "  ".join(cells), kind


def node_detail_lines(node):
    free_gpu = node["gpu_total"] - node["gpu_alloc"]
    free_cpu = node["cpu_total"] - node["cpu_alloc"]
    free_mem = node["mem_total"] - node["mem_alloc"]

    lines = [
        f"Node        {node['name']}",
        f"State       {'+'.join(node['states']) or 'UNKNOWN'}",
        f"Partitions  {','.join(node['partitions']) or 'none'}",
        f"Status      {BUCKET_LABEL[classify(node)]}",
        "",
    ]
    if node["gpu_total"]:
        lines.append(
            f"GPU         {free_gpu} free of {node['gpu_total']}"
            f"  ({node['gpu_type'] or 'unknown type'})  {bar(free_gpu, node['gpu_total'])}"
        )
    lines.append(
        f"CPU         {free_cpu} free of {node['cpu_total']}  {bar(free_cpu, node['cpu_total'])}"
    )
    lines.append(
        f"RAM         {format_memory(free_mem)} free of {format_memory(node['mem_total'])}"
        f"  {bar(free_mem, node['mem_total'])}"
    )
    if node["reason"] and node["reason"] != "(null)":
        lines.extend(["", "Reason", f"  {node['reason']}"])
    return lines


class Browser:
    def __init__(self, screen, nodes, host, reload_nodes=None):
        self.screen = screen
        self.host = host
        self.reload_nodes = reload_nodes
        self.status = ""
        self.set_nodes(nodes)

    def set_nodes(self, nodes):
        self.nodes = nodes
        self.groups = group_nodes(nodes)
        self.totals = summarize(nodes)
        self.level = "groups"
        self.group_index = 0
        self.node_index = 0
        self.offset = 0
        self.bucket = None
        self.search = ""
        self.selected_node = None

    # -- state helpers -------------------------------------------------

    @property
    def current_group(self):
        return self.groups[self.group_index]

    def visible_nodes(self):
        return sort_nodes(filter_nodes(self.current_group[1], self.bucket, self.search))

    def rows(self):
        """Rows for the current level as (text, sub_text, colour kind, payload)."""
        if self.level == "groups":
            groups = self.groups
            if self.search:
                needle = self.search.lower()
                groups = [g for g in groups if needle in group_label(g[0]).lower()]
            return [(*group_row(*group), group) for group in groups]

        show_gpu = bool(self.current_group[0][1])
        rows = []
        for node in self.visible_nodes():
            text, kind = node_row(node, show_gpu)
            rows.append((text, node["reason"], kind, node))
        return rows

    def index(self):
        return self.group_index if self.level == "groups" else self.node_index

    def set_index(self, value, count):
        value = 0 if count == 0 else max(0, min(count - 1, value))
        if self.level == "groups":
            self.group_index = value
        else:
            self.node_index = value

    # -- drawing -------------------------------------------------------

    def write(self, y, x, text, attr=0):
        height, width = self.screen.getmaxyx()
        if y < 0 or y >= height or x >= width:
            return
        try:
            self.screen.addnstr(y, x, text, max(0, width - x - 1), attr)
        except curses.error:
            pass

    def color(self, kind, extra=0):
        if not curses.has_colors():
            return extra
        return curses.color_pair(COLORS.get(kind, 0)) | extra

    def draw_header(self, width):
        totals = self.totals
        title = f" Slurm resources on {self.host} "
        self.write(0, 0, title.ljust(width), self.color("header", curses.A_BOLD))

        summary = (
            f"GPUs {totals['gpu_free']}/{totals['gpu_total']}"
            f"   CPUs {totals['cpu_free']}/{totals['cpu_total']}"
            f"   RAM {format_memory(totals['mem_free'])}/{format_memory(totals['mem_total'])}"
            f"   nodes {totals['usable']}/{totals['nodes']} usable"
        )
        self.write(1, 1, summary, curses.A_BOLD)

        if self.level == "groups":
            crumb = f"{len(self.groups)} resource groups"
        else:
            key, group = self.current_group
            crumb = (
                f"{group_label(key)}  ·  filter: {BUCKET_LABEL.get(self.bucket, 'all')}"
                f"  ·  showing {len(self.rows())} of {len(group)} nodes"
            )
        if self.search:
            crumb += f"  ·  search: {self.search}"
        self.write(2, 1, crumb, self.color("dim"))

    def draw_footer(self, height, width):
        help_text = GROUPS_HELP if self.level == "groups" else NODES_HELP
        if self.level == "detail":
            help_text = DETAIL_HELP
        text = self.status or help_text
        self.write(height - 1, 0, (" " + text).ljust(width), self.color("header"))

    def draw_list(self, rows, top, body_height):
        count = len(rows)
        self.set_index(self.index(), count)
        selected = self.index()

        if selected < self.offset:
            self.offset = selected
        elif selected >= self.offset + body_height:
            self.offset = selected - body_height + 1
        self.offset = max(0, min(self.offset, max(0, count - body_height)))

        if not count:
            self.write(top, 2, "nothing matches the current filter", self.color("dim"))
            return

        line = top
        for position in range(self.offset, min(count, self.offset + body_height)):
            row = rows[position]
            attr = self.color(row[2])
            if position == selected:
                attr |= curses.A_REVERSE
            marker = "›" if position == selected else " "
            self.write(line, 0, f"{marker} {row[0]}", attr)
            line += 1
            if self.level == "groups" and line < top + body_height:
                sub_attr = self.color("dim") | (curses.A_REVERSE if position == selected else 0)
                self.write(line, 2, f"  {row[1]}", sub_attr)
                line += 1
            if line >= top + body_height:
                break

    def draw_detail(self, node, top, body_height):
        for offset, line in enumerate(node_detail_lines(node)):
            if offset >= body_height:
                break
            attr = curses.A_BOLD if offset == 0 else 0
            self.write(top + offset, 2, line, attr)

    def draw(self):
        self.screen.erase()
        height, width = self.screen.getmaxyx()
        self.draw_header(width)
        top = 4
        body_height = max(1, height - top - 1)

        if self.level == "detail":
            self.draw_detail(self.selected_node, top, body_height)
        else:
            rows = self.rows()
            if self.level == "groups":
                body_height = max(1, body_height)
            self.draw_list(rows, top, body_height)

        self.draw_footer(height, width)
        self.screen.noutrefresh()
        curses.doupdate()

    # -- input ---------------------------------------------------------

    def prompt(self, label):
        height, width = self.screen.getmaxyx()
        buffer = ""
        while True:
            self.write(height - 1, 0, f" {label}{buffer}".ljust(width), curses.A_REVERSE)
            self.screen.refresh()
            key = self.screen.getch()
            if key in (curses.KEY_ENTER, 10, 13):
                return buffer
            if key == 27:
                return None
            if key in (curses.KEY_BACKSPACE, 127, 8):
                buffer = buffer[:-1]
            elif 32 <= key < 127:
                buffer += chr(key)

    def refresh_nodes(self):
        if not self.reload_nodes:
            return
        self.status = "Refreshing..."
        self.draw()
        try:
            nodes = self.reload_nodes()
        except RuntimeError as error:
            self.status = f"Refresh failed: {error}"
            return
        self.set_nodes(nodes)
        self.status = ""

    def handle(self, key, body_height):
        count = len(self.rows()) if self.level != "detail" else 0

        if key in (ord("q"), ord("Q")):
            return False
        if key == curses.KEY_RESIZE:
            return True

        self.status = ""

        if self.level == "detail":
            if key in (curses.KEY_LEFT, 27, curses.KEY_BACKSPACE, 127, 8, 10, 13):
                self.level = "nodes"
            return True

        if key in (curses.KEY_DOWN, ord("j")):
            self.set_index(self.index() + 1, count)
        elif key in (curses.KEY_UP, ord("k")):
            self.set_index(self.index() - 1, count)
        elif key == curses.KEY_NPAGE:
            self.set_index(self.index() + body_height, count)
        elif key == curses.KEY_PPAGE:
            self.set_index(self.index() - body_height, count)
        elif key == curses.KEY_HOME:
            self.set_index(0, count)
        elif key == curses.KEY_END:
            self.set_index(count - 1, count)
        elif key in (curses.KEY_RIGHT, curses.KEY_ENTER, 10, 13):
            if self.level == "groups" and self.groups:
                self.level = "nodes"
                self.node_index = 0
                self.offset = 0
                self.search = ""
            elif self.level == "nodes" and count:
                self.selected_node = self.rows()[self.node_index][3]
                self.level = "detail"
        elif key in (curses.KEY_LEFT, curses.KEY_BACKSPACE, 127, 8):
            if self.level == "nodes":
                self.level = "groups"
                self.offset = 0
                self.search = ""
                self.bucket = None
        elif key == ord("/"):
            entered = self.prompt("search: ")
            if entered is not None:
                self.search = entered
                self.offset = 0
                self.set_index(0, len(self.rows()))
        elif key == 27:
            self.search = ""
        elif key in (ord("r"), ord("R")):
            self.refresh_nodes()
        elif self.level == "nodes" and 0 <= key < 256 and chr(key) in FILTERS:
            self.bucket = FILTERS[chr(key)]
            self.offset = 0
            self.node_index = 0

        return True

    def run(self):
        curses.curs_set(0)
        self.screen.keypad(True)
        while True:
            self.draw()
            height, _ = self.screen.getmaxyx()
            body_height = max(1, height - 5)
            key = self.screen.getch()
            if not self.handle(key, body_height):
                return


def init_colors():
    if not curses.has_colors():
        return
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(COLORS["free"], curses.COLOR_GREEN, -1)
    curses.init_pair(COLORS["partial"], curses.COLOR_YELLOW, -1)
    curses.init_pair(COLORS["full"], curses.COLOR_RED, -1)
    curses.init_pair(COLORS["unavailable"], curses.COLOR_MAGENTA, -1)
    curses.init_pair(COLORS["header"], curses.COLOR_BLACK, curses.COLOR_CYAN)
    curses.init_pair(COLORS["dim"], curses.COLOR_CYAN, -1)


def run(nodes, host, reload_nodes=None):
    locale.setlocale(locale.LC_ALL, "")

    def start(screen):
        init_colors()
        Browser(screen, nodes, host, reload_nodes).run()

    curses.wrapper(start)
