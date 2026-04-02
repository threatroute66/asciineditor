#!/usr/bin/env python3
"""asciineditor GUI - A graphical editor for asciicast v2 (.cast) files.

Built with tkinter (Python standard library). No external dependencies.
"""

import copy
import json
import os
import re
import time
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

# ── Core I/O (shared with CLI) ──────────────────────────────────────────────

def read_cast(path):
    with open(path, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()
    if not lines:
        raise ValueError(f"'{path}' is empty.")
    header = json.loads(lines[0])
    if header.get("version") != 2:
        raise ValueError(f"'{path}' is not asciicast v2.")
    events = []
    for line in lines[1:]:
        if line.strip():
            events.append(json.loads(line))
    return header, events


def write_cast(path, header, events):
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps(header, ensure_ascii=False) + "\n")
        for ev in events:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")


def update_duration(header, events):
    header["duration"] = events[-1][0] if events else 0.0


# ── Colors ───────────────────────────────────────────────────────────────────

COL_BG = "#1e1e2e"
COL_SURFACE = "#313244"
COL_OVERLAY = "#45475a"
COL_TEXT = "#cdd6f4"
COL_SUBTEXT = "#a6adc8"
COL_ACCENT = "#89b4fa"
COL_GREEN = "#a6e3a1"
COL_RED = "#f38ba8"
COL_YELLOW = "#f9e2af"
COL_MAUVE = "#cba6f7"
COL_TEAL = "#94e2d5"
COL_MARKER = "#f9e2af"
COL_START = "#a6e3a1"
COL_END = "#f38ba8"
COL_SELECTION = "#89b4fa"
COL_EVENT_TICK = "#585b70"
COL_TIMELINE_BG = "#181825"
COL_PLAYHEAD = "#f5c2e7"

# Standard 8 terminal colors + bright variants
TERM_COLORS = [
    "#45475a", "#f38ba8", "#a6e3a1", "#f9e2af",
    "#89b4fa", "#cba6f7", "#94e2d5", "#bac2de",
    "#585b70", "#f38ba8", "#a6e3a1", "#f9e2af",
    "#89b4fa", "#cba6f7", "#94e2d5", "#a6adc8",
]
TERM_FG_DEFAULT = "#cdd6f4"
TERM_BG_DEFAULT = "#11111b"


# ── ANSI Parser ─────────────────────────────────────────────────────────────

# Regex to match CSI sequences: ESC [ <params> <final byte>
_CSI_RE = re.compile(r'\x1b\[([0-9;?]*)([A-Za-z@`])')
# Regex to match OSC sequences: ESC ] ... ST  (ST = ESC\ or BEL)
_OSC_RE = re.compile(r'\x1b\].*?(?:\x1b\\|\x07)')
# Other escape sequences to strip
_OTHER_ESC_RE = re.compile(r'\x1b[()][0-9A-B]|\x1b[=>Nc]|\x1b\[[\?0-9;]*[hlsr]')


class TerminalBuffer:
    """Minimal virtual terminal buffer that tracks cursor and basic SGR colors."""

    def __init__(self, cols, rows):
        self.cols = cols
        self.rows = rows
        self.cursor_row = 0
        self.cursor_col = 0
        # Each cell: (char, fg_color, bg_color, bold)
        self.fg = TERM_FG_DEFAULT
        self.bg = TERM_BG_DEFAULT
        self.bold = False
        self.cells = self._empty_screen()

    def _empty_screen(self):
        return [[(" ", TERM_FG_DEFAULT, TERM_BG_DEFAULT, False)
                 for _ in range(self.cols)] for _ in range(self.rows)]

    def _empty_row(self):
        return [(" ", TERM_FG_DEFAULT, TERM_BG_DEFAULT, False)
                for _ in range(self.cols)]

    def _scroll_up(self):
        self.cells.pop(0)
        self.cells.append(self._empty_row())

    def clear(self):
        self.cells = self._empty_screen()
        self.cursor_row = 0
        self.cursor_col = 0

    def _apply_sgr(self, params_str):
        """Apply Select Graphic Rendition parameters."""
        if not params_str:
            params = [0]
        else:
            params = [int(p) if p else 0 for p in params_str.split(";")]

        i = 0
        while i < len(params):
            p = params[i]
            if p == 0:
                self.fg = TERM_FG_DEFAULT
                self.bg = TERM_BG_DEFAULT
                self.bold = False
            elif p == 1:
                self.bold = True
            elif p == 22:
                self.bold = False
            elif p == 7:  # reverse video
                self.fg, self.bg = self.bg, self.fg
            elif p == 27:  # reverse off
                self.fg, self.bg = self.bg, self.fg
            elif 30 <= p <= 37:
                idx = p - 30
                if self.bold:
                    idx += 8
                self.fg = TERM_COLORS[idx]
            elif p == 38:
                # Extended foreground: 38;5;N or 38;2;R;G;B
                if i + 1 < len(params) and params[i + 1] == 5 and i + 2 < len(params):
                    n = params[i + 2]
                    self.fg = self._color_256(n)
                    i += 2
                elif i + 1 < len(params) and params[i + 1] == 2 and i + 4 < len(params):
                    r, g, b = params[i + 2], params[i + 3], params[i + 4]
                    self.fg = f"#{r:02x}{g:02x}{b:02x}"
                    i += 4
            elif p == 39:
                self.fg = TERM_FG_DEFAULT
            elif 40 <= p <= 47:
                idx = p - 40
                self.bg = TERM_COLORS[idx]
            elif p == 48:
                if i + 1 < len(params) and params[i + 1] == 5 and i + 2 < len(params):
                    n = params[i + 2]
                    self.bg = self._color_256(n)
                    i += 2
                elif i + 1 < len(params) and params[i + 1] == 2 and i + 4 < len(params):
                    r, g, b = params[i + 2], params[i + 3], params[i + 4]
                    self.bg = f"#{r:02x}{g:02x}{b:02x}"
                    i += 4
            elif p == 49:
                self.bg = TERM_BG_DEFAULT
            elif 90 <= p <= 97:
                self.fg = TERM_COLORS[p - 90 + 8]
            elif 100 <= p <= 107:
                self.bg = TERM_COLORS[p - 100 + 8]
            i += 1

    def _color_256(self, n):
        if n < 16:
            return TERM_COLORS[n]
        elif n < 232:
            n -= 16
            b = (n % 6) * 51
            g = ((n // 6) % 6) * 51
            r = (n // 36) * 51
            return f"#{r:02x}{g:02x}{b:02x}"
        else:
            v = 8 + (n - 232) * 10
            return f"#{v:02x}{v:02x}{v:02x}"

    def _erase_in_line(self, mode):
        if mode == 0:  # cursor to end
            for c in range(self.cursor_col, self.cols):
                self.cells[self.cursor_row][c] = (" ", TERM_FG_DEFAULT, TERM_BG_DEFAULT, False)
        elif mode == 1:  # start to cursor
            for c in range(0, self.cursor_col + 1):
                self.cells[self.cursor_row][c] = (" ", TERM_FG_DEFAULT, TERM_BG_DEFAULT, False)
        elif mode == 2:  # entire line
            self.cells[self.cursor_row] = self._empty_row()

    def _erase_in_display(self, mode):
        if mode == 0:  # cursor to end
            self._erase_in_line(0)
            for r in range(self.cursor_row + 1, self.rows):
                self.cells[r] = self._empty_row()
        elif mode == 1:  # start to cursor
            for r in range(0, self.cursor_row):
                self.cells[r] = self._empty_row()
            self._erase_in_line(1)
        elif mode in (2, 3):  # entire screen
            self.cells = self._empty_screen()

    def feed(self, data):
        """Process a chunk of terminal output data."""
        pos = 0
        while pos < len(data):
            # Try CSI sequence
            m = _CSI_RE.match(data, pos)
            if m:
                params_str = m.group(1)
                cmd = m.group(2)
                self._handle_csi(params_str, cmd)
                pos = m.end()
                continue

            # Try OSC sequence
            m = _OSC_RE.match(data, pos)
            if m:
                pos = m.end()
                continue

            # Try other escape sequences
            m = _OTHER_ESC_RE.match(data, pos)
            if m:
                pos = m.end()
                continue

            # Skip standalone ESC + one char we don't handle
            if data[pos] == '\x1b' and pos + 1 < len(data):
                pos += 2
                continue

            ch = data[pos]
            pos += 1

            if ch == '\r':
                self.cursor_col = 0
            elif ch == '\n':
                self.cursor_row += 1
                if self.cursor_row >= self.rows:
                    self.cursor_row = self.rows - 1
                    self._scroll_up()
            elif ch == '\x08':  # backspace
                if self.cursor_col > 0:
                    self.cursor_col -= 1
            elif ch == '\x07':  # bell
                pass
            elif ch == '\t':
                next_tab = (self.cursor_col // 8 + 1) * 8
                self.cursor_col = min(next_tab, self.cols - 1)
            elif ch >= ' ' or ord(ch) > 127:
                if self.cursor_col >= self.cols:
                    self.cursor_col = 0
                    self.cursor_row += 1
                    if self.cursor_row >= self.rows:
                        self.cursor_row = self.rows - 1
                        self._scroll_up()
                self.cells[self.cursor_row][self.cursor_col] = (
                    ch, self.fg, self.bg, self.bold)
                self.cursor_col += 1

    def _handle_csi(self, params_str, cmd):
        params = []
        if params_str and not params_str.startswith("?"):
            params = [int(p) if p else 0 for p in params_str.split(";")]

        if cmd == 'm':
            self._apply_sgr(params_str)
        elif cmd == 'H' or cmd == 'f':  # cursor position
            row = (params[0] if params else 1) - 1
            col = (params[1] if len(params) > 1 else 1) - 1
            self.cursor_row = max(0, min(self.rows - 1, row))
            self.cursor_col = max(0, min(self.cols - 1, col))
        elif cmd == 'A':  # cursor up
            n = params[0] if params else 1
            self.cursor_row = max(0, self.cursor_row - n)
        elif cmd == 'B':  # cursor down
            n = params[0] if params else 1
            self.cursor_row = min(self.rows - 1, self.cursor_row + n)
        elif cmd == 'C':  # cursor forward
            n = params[0] if params else 1
            self.cursor_col = min(self.cols - 1, self.cursor_col + n)
        elif cmd == 'D':  # cursor backward
            n = params[0] if params else 1
            self.cursor_col = max(0, self.cursor_col - n)
        elif cmd == 'G':  # cursor horizontal absolute
            col = (params[0] if params else 1) - 1
            self.cursor_col = max(0, min(self.cols - 1, col))
        elif cmd == 'J':  # erase in display
            mode = params[0] if params else 0
            self._erase_in_display(mode)
        elif cmd == 'K':  # erase in line
            mode = params[0] if params else 0
            self._erase_in_line(mode)
        elif cmd == 'P':  # delete characters
            n = params[0] if params else 1
            row = self.cells[self.cursor_row]
            for _ in range(n):
                if self.cursor_col < len(row):
                    row.pop(self.cursor_col)
                    row.append((" ", TERM_FG_DEFAULT, TERM_BG_DEFAULT, False))
        elif cmd == 'L':  # insert lines
            n = params[0] if params else 1
            for _ in range(n):
                if self.cursor_row < self.rows:
                    self.cells.insert(self.cursor_row, self._empty_row())
                    self.cells.pop()
        elif cmd == 'M':  # delete lines
            n = params[0] if params else 1
            for _ in range(n):
                if self.cursor_row < self.rows:
                    self.cells.pop(self.cursor_row)
                    self.cells.append(self._empty_row())
        elif cmd == 'd':  # vertical position absolute
            row = (params[0] if params else 1) - 1
            self.cursor_row = max(0, min(self.rows - 1, row))
        elif cmd == '@':  # insert blank characters
            n = params[0] if params else 1
            row = self.cells[self.cursor_row]
            for _ in range(n):
                row.insert(self.cursor_col,
                           (" ", TERM_FG_DEFAULT, TERM_BG_DEFAULT, False))
                if len(row) > self.cols:
                    row.pop()


# ── Application ─────────────────────────────────────────────────────────────

class AsciineditorGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("asciineditor")
        self.root.geometry("1200x820")
        self.root.configure(bg=COL_BG)
        self.root.minsize(900, 600)

        # State
        self.file_path = None
        self.header = None
        self.events = []
        self.duration = 0.0
        self.start_marker = None  # timestamp
        self.end_marker = None    # timestamp
        self.marker_mode = None   # "start", "end", or None
        self.undo_stack = []

        # Playback state
        self.playing = False
        self.play_speed = 1.0
        self.play_event_idx = 0
        self.play_start_wall = 0.0    # wall-clock time when playback started
        self.play_start_ts = 0.0      # cast timestamp when playback started
        self.playhead_ts = 0.0
        self._play_after_id = None
        self.term_buffer = None

        self._build_ui()
        self._bind_keys()

    # ── UI Construction ──────────────────────────────────────────────────

    def _build_ui(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame", background=COL_BG)
        style.configure("TLabel", background=COL_BG, foreground=COL_TEXT,
                         font=("monospace", 10))
        style.configure("TButton", background=COL_SURFACE, foreground=COL_TEXT,
                         font=("monospace", 10), borderwidth=1, relief="flat",
                         padding=(10, 5))
        style.map("TButton",
                  background=[("active", COL_OVERLAY), ("disabled", COL_BG)],
                  foreground=[("disabled", COL_OVERLAY)])
        style.configure("Accent.TButton", background=COL_ACCENT, foreground=COL_BG,
                         font=("monospace", 10, "bold"))
        style.map("Accent.TButton",
                  background=[("active", COL_MAUVE)])
        style.configure("Start.TButton", background=COL_GREEN, foreground=COL_BG,
                         font=("monospace", 10, "bold"))
        style.map("Start.TButton", background=[("active", "#77d490")])
        style.configure("End.TButton", background=COL_RED, foreground=COL_BG,
                         font=("monospace", 10, "bold"))
        style.map("End.TButton", background=[("active", "#e07090")])
        style.configure("Clear.TButton", background=COL_YELLOW, foreground=COL_BG,
                         font=("monospace", 10, "bold"))
        style.map("Clear.TButton", background=[("active", "#e0c880")])
        style.configure("Play.TButton", background=COL_GREEN, foreground=COL_BG,
                         font=("monospace", 10, "bold"))
        style.map("Play.TButton", background=[("active", "#77d490")])
        style.configure("TLabelframe", background=COL_BG, foreground=COL_ACCENT,
                         font=("monospace", 10))
        style.configure("TLabelframe.Label", background=COL_BG, foreground=COL_ACCENT,
                         font=("monospace", 10, "bold"))
        style.configure("Treeview", background=COL_SURFACE, foreground=COL_TEXT,
                         fieldbackground=COL_SURFACE, font=("monospace", 9),
                         rowheight=22)
        style.configure("Treeview.Heading", background=COL_OVERLAY, foreground=COL_TEXT,
                         font=("monospace", 9, "bold"))
        style.map("Treeview", background=[("selected", COL_OVERLAY)])
        style.configure("TScale", background=COL_BG, troughcolor=COL_SURFACE)

        # ── Top toolbar ──
        toolbar = ttk.Frame(self.root)
        toolbar.pack(fill=tk.X, padx=8, pady=(8, 4))

        ttk.Button(toolbar, text="Open", style="Accent.TButton",
                   command=self.open_file).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(toolbar, text="Save As", command=self.save_as).pack(side=tk.LEFT, padx=4)
        ttk.Button(toolbar, text="Undo", command=self.undo).pack(side=tk.LEFT, padx=4)

        sep = ttk.Frame(toolbar, width=20)
        sep.pack(side=tk.LEFT, padx=4)

        ttk.Button(toolbar, text="Join Files", command=self.join_files).pack(side=tk.LEFT, padx=4)

        # ── File info ──
        self.info_var = tk.StringVar(value="No file loaded")
        ttk.Label(self.root, textvariable=self.info_var,
                  font=("monospace", 9), foreground=COL_SUBTEXT).pack(
            fill=tk.X, padx=10, pady=(4, 2))

        # ── Timeline frame ──
        tl_frame = ttk.LabelFrame(self.root, text="Timeline")
        tl_frame.pack(fill=tk.X, padx=8, pady=4)

        self.timeline = tk.Canvas(tl_frame, height=80, bg=COL_TIMELINE_BG,
                                  highlightthickness=0, cursor="crosshair")
        self.timeline.pack(fill=tk.X, padx=6, pady=6)
        self.timeline.bind("<Button-1>", self._on_timeline_click)
        self.timeline.bind("<Configure>", lambda e: self._draw_timeline())
        self.timeline.bind("<Motion>", self._on_timeline_hover)

        # ── Marker + Playback controls ──
        ctrl_frame = ttk.Frame(self.root)
        ctrl_frame.pack(fill=tk.X, padx=8, pady=2)

        # Marker buttons
        ttk.Button(ctrl_frame, text="Set Start", style="Start.TButton",
                   command=lambda: self._set_marker_mode("start")).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(ctrl_frame, text="Set End", style="End.TButton",
                   command=lambda: self._set_marker_mode("end")).pack(side=tk.LEFT, padx=4)
        ttk.Button(ctrl_frame, text="Clear Markers", style="Clear.TButton",
                   command=self._clear_markers).pack(side=tk.LEFT, padx=4)

        # Separator
        ttk.Frame(ctrl_frame, width=15).pack(side=tk.LEFT)

        # Playback buttons
        self.play_btn = ttk.Button(ctrl_frame, text="Play", style="Play.TButton",
                                    command=self.play_toggle)
        self.play_btn.pack(side=tk.LEFT, padx=4)
        ttk.Button(ctrl_frame, text="Stop",
                   command=self.play_stop).pack(side=tk.LEFT, padx=4)

        # Speed control
        ttk.Label(ctrl_frame, text="Speed:", font=("monospace", 9),
                  foreground=COL_SUBTEXT).pack(side=tk.LEFT, padx=(12, 2))
        self.speed_var = tk.DoubleVar(value=1.0)
        speed_scale = ttk.Scale(ctrl_frame, from_=0.25, to=4.0,
                                variable=self.speed_var, orient=tk.HORIZONTAL,
                                length=120, command=self._on_speed_change)
        speed_scale.pack(side=tk.LEFT, padx=2)
        self.speed_label = ttk.Label(ctrl_frame, text="1.0x",
                                      font=("monospace", 9), foreground=COL_SUBTEXT)
        self.speed_label.pack(side=tk.LEFT, padx=(2, 8))

        # Playback time display
        self.play_time_var = tk.StringVar(value="")
        ttk.Label(ctrl_frame, textvariable=self.play_time_var,
                  font=("monospace", 9), foreground=COL_ACCENT).pack(side=tk.LEFT, padx=4)

        # Marker info
        self.marker_info = tk.StringVar(value="")
        ttk.Label(ctrl_frame, textvariable=self.marker_info,
                  font=("monospace", 9), foreground=COL_SUBTEXT).pack(
            side=tk.RIGHT, padx=4)

        # ── Operation buttons ──
        ops_frame = ttk.LabelFrame(self.root, text="Operations")
        ops_frame.pack(fill=tk.X, padx=8, pady=4)
        ops_inner = ttk.Frame(ops_frame)
        ops_inner.pack(padx=6, pady=6)

        ttk.Button(ops_inner, text="Split at Start Marker",
                   command=self.do_split).pack(side=tk.LEFT, padx=4)
        ttk.Button(ops_inner, text="Cut Selection",
                   command=self.do_cut).pack(side=tk.LEFT, padx=4)
        ttk.Button(ops_inner, text="Save Selection",
                   command=self.do_save_selection).pack(side=tk.LEFT, padx=4)
        ttk.Button(ops_inner, text="Speed Up Selection",
                   command=lambda: self.do_speed(2.0)).pack(side=tk.LEFT, padx=4)
        ttk.Button(ops_inner, text="Slow Down Selection",
                   command=lambda: self.do_speed(0.5)).pack(side=tk.LEFT, padx=4)
        ttk.Button(ops_inner, text="Custom Speed...",
                   command=self.do_speed_custom).pack(side=tk.LEFT, padx=4)
        ttk.Button(ops_inner, text="Add Marker...",
                   command=self.do_add_marker).pack(side=tk.LEFT, padx=4)
        ttk.Button(ops_inner, text="Remove Markers...",
                   command=self.do_remove_markers).pack(side=tk.LEFT, padx=4)

        # ── Main content area: Terminal + Events side by side ──
        content_pane = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        content_pane.pack(fill=tk.BOTH, expand=True, padx=8, pady=(4, 8))

        # Terminal display
        term_frame = ttk.LabelFrame(self.root, text="Terminal")
        content_pane.add(term_frame, weight=3)

        self.term_display = tk.Text(
            term_frame, wrap=tk.NONE, state=tk.DISABLED,
            bg=TERM_BG_DEFAULT, fg=TERM_FG_DEFAULT,
            font=("monospace", 10), insertbackground=COL_GREEN,
            highlightthickness=0, borderwidth=0, padx=4, pady=4,
            cursor="arrow",
        )
        self.term_display.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        # Event list
        list_frame = ttk.LabelFrame(self.root, text="Events")
        content_pane.add(list_frame, weight=2)

        cols = ("time", "type", "data")
        self.tree = ttk.Treeview(list_frame, columns=cols, show="headings",
                                 selectmode="browse")
        self.tree.heading("time", text="Time (s)")
        self.tree.heading("type", text="Type")
        self.tree.heading("data", text="Data")
        self.tree.column("time", width=80, stretch=False)
        self.tree.column("type", width=55, stretch=False)
        self.tree.column("data", width=300)

        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL,
                                  command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(6, 0), pady=6)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 6), pady=6)

        # Right-click context menu for event list
        self.tree_menu = tk.Menu(self.root, tearoff=0, bg=COL_SURFACE, fg=COL_TEXT,
                                 activebackground=COL_OVERLAY, activeforeground=COL_TEXT)
        self.tree_menu.add_command(label="Remove this marker", command=self._remove_selected_marker)
        self.tree.bind("<Button-3>", self._on_tree_right_click)

        # Tooltip label for timeline
        self.hover_var = tk.StringVar(value="")
        self.hover_label = tk.Label(self.root, textvariable=self.hover_var,
                                    bg=COL_OVERLAY, fg=COL_TEXT,
                                    font=("monospace", 9), padx=4, pady=2)

    def _bind_keys(self):
        self.root.bind("<Control-o>", lambda e: self.open_file())
        self.root.bind("<Control-s>", lambda e: self.save_as())
        self.root.bind("<Control-z>", lambda e: self.undo())
        self.root.bind("<space>", lambda e: self.play_toggle())

    # ── File I/O ─────────────────────────────────────────────────────────

    def open_file(self):
        path = filedialog.askopenfilename(
            title="Open asciicast file",
            filetypes=[("Asciicast files", "*.cast"), ("All files", "*.*")])
        if not path:
            return
        try:
            header, events = read_cast(path)
        except Exception as e:
            messagebox.showerror("Error", str(e))
            return
        self.play_stop()
        self.file_path = path
        self.header = header
        self.events = events
        self.duration = events[-1][0] if events else 0.0
        self.start_marker = None
        self.end_marker = None
        self.marker_mode = None
        self.undo_stack.clear()
        self._init_term_buffer()
        self._refresh()
        self._render_term_at(0)

    def save_as(self):
        if not self.header:
            messagebox.showinfo("Info", "No file loaded.")
            return
        path = filedialog.asksaveasfilename(
            title="Save asciicast file",
            defaultextension=".cast",
            filetypes=[("Asciicast files", "*.cast"), ("All files", "*.*")])
        if not path:
            return
        try:
            h = copy.deepcopy(self.header)
            update_duration(h, self.events)
            write_cast(path, h, self.events)
            self.file_path = path
            messagebox.showinfo("Saved", f"Saved to {path}")
            self._update_info()
        except Exception as e:
            messagebox.showerror("Error", str(e))

    # ── Undo ─────────────────────────────────────────────────────────────

    def _push_undo(self):
        self.undo_stack.append((
            copy.deepcopy(self.header),
            copy.deepcopy(self.events),
            self.start_marker,
            self.end_marker,
        ))
        if len(self.undo_stack) > 30:
            self.undo_stack.pop(0)

    def undo(self):
        if not self.undo_stack:
            messagebox.showinfo("Undo", "Nothing to undo.")
            return
        self.play_stop()
        self.header, self.events, self.start_marker, self.end_marker = self.undo_stack.pop()
        self.duration = self.events[-1][0] if self.events else 0.0
        self._init_term_buffer()
        self._refresh()

    # ── Terminal Buffer ──────────────────────────────────────────────────

    def _init_term_buffer(self):
        cols = self.header.get("width", 80) if self.header else 80
        rows = self.header.get("height", 24) if self.header else 24
        self.term_buffer = TerminalBuffer(cols, rows)
        self.term_display.configure(
            width=cols, height=rows,
        )

    def _render_term_at(self, up_to_event_idx):
        """Replay events 0..up_to_event_idx into the terminal buffer and render."""
        if not self.term_buffer:
            self._init_term_buffer()
        self.term_buffer.clear()
        for i in range(up_to_event_idx + 1):
            if i >= len(self.events):
                break
            ev = self.events[i]
            if ev[1] == "o":
                self.term_buffer.feed(ev[2])
        self._paint_term()

    def _render_term_feed(self, data):
        """Feed data into the existing buffer and repaint."""
        if self.term_buffer:
            self.term_buffer.feed(data)
            self._paint_term()

    def _paint_term(self):
        """Render the TerminalBuffer contents into the Text widget."""
        buf = self.term_buffer
        if not buf:
            return

        self.term_display.configure(state=tk.NORMAL)
        self.term_display.delete("1.0", tk.END)

        # Build color tags as needed
        used_tags = set()

        lines = []
        for r in range(buf.rows):
            for c in range(buf.cols):
                ch, fg, bg, bold = buf.cells[r][c]
                tag = f"c_{fg}_{bg}_{int(bold)}"
                if tag not in used_tags:
                    used_tags.add(tag)
                    font = ("monospace", 10, "bold") if bold else ("monospace", 10)
                    bg_actual = bg if bg != TERM_BG_DEFAULT else ""
                    self.term_display.tag_configure(
                        tag, foreground=fg, font=font,
                        **({} if not bg_actual else {"background": bg_actual}))
                self.term_display.insert(tk.END, ch, tag)
            if r < buf.rows - 1:
                self.term_display.insert(tk.END, "\n")

        # Show cursor
        cursor_pos = f"{buf.cursor_row + 1}.{buf.cursor_col}"
        try:
            self.term_display.tag_add("cursor", cursor_pos, f"{cursor_pos}+1c")
            self.term_display.tag_configure("cursor", background=COL_GREEN, foreground=TERM_BG_DEFAULT)
        except tk.TclError:
            pass

        self.term_display.configure(state=tk.DISABLED)

    # ── Playback ─────────────────────────────────────────────────────────

    def play_toggle(self):
        if not self.events:
            return
        if self.playing:
            self._play_pause()
        else:
            self._play_start()

    def _play_start(self):
        if not self.events:
            return
        # If at end, restart
        if self.play_event_idx >= len(self.events):
            self.play_event_idx = 0
            self._init_term_buffer()

        self.playing = True
        self.play_btn.configure(text="Pause")
        self.play_speed = self.speed_var.get()
        self.play_start_wall = time.monotonic()
        self.play_start_ts = self.events[self.play_event_idx][0] if self.play_event_idx < len(self.events) else 0.0

        # Render up to current position
        if self.play_event_idx > 0:
            self._render_term_at(self.play_event_idx - 1)
        else:
            self._init_term_buffer()
            self._paint_term()

        self._play_schedule_next()

    def _play_pause(self):
        self.playing = False
        self.play_btn.configure(text="Play")
        if self._play_after_id:
            self.root.after_cancel(self._play_after_id)
            self._play_after_id = None

    def play_stop(self):
        self.playing = False
        self.play_btn.configure(text="Play")
        if self._play_after_id:
            self.root.after_cancel(self._play_after_id)
            self._play_after_id = None
        self.play_event_idx = 0
        self.playhead_ts = 0.0
        self.play_time_var.set("")
        self._init_term_buffer()
        self._paint_term()
        self._draw_timeline()

    def _play_schedule_next(self):
        if not self.playing or self.play_event_idx >= len(self.events):
            if self.playing:
                self.playing = False
                self.play_btn.configure(text="Play")
                self.play_time_var.set(f"{self.duration:.2f}s / {self.duration:.2f}s  (done)")
            return

        ev = self.events[self.play_event_idx]
        event_ts = ev[0]

        # Compute wall-clock delay
        elapsed_cast = event_ts - self.play_start_ts
        elapsed_wall = elapsed_cast / self.play_speed if self.play_speed > 0 else 0
        target_wall = self.play_start_wall + elapsed_wall
        now = time.monotonic()
        delay_ms = max(1, int((target_wall - now) * 1000))

        self._play_after_id = self.root.after(delay_ms, self._play_tick)

    def _play_tick(self):
        if not self.playing or self.play_event_idx >= len(self.events):
            return

        ev = self.events[self.play_event_idx]
        self.playhead_ts = ev[0]

        # Feed event to terminal
        if ev[1] == "o":
            self._render_term_feed(ev[2])

        # Update time display
        self.play_time_var.set(f"{self.playhead_ts:.2f}s / {self.duration:.2f}s")

        # Highlight current event in tree
        self._highlight_event(self.play_event_idx)

        # Update playhead on timeline
        self._draw_timeline()

        self.play_event_idx += 1
        self._play_schedule_next()

    def _on_speed_change(self, val):
        speed = round(float(val), 2)
        self.speed_label.configure(text=f"{speed:.1f}x")
        if self.playing:
            # Recalibrate timing
            self.play_speed = speed
            self.play_start_wall = time.monotonic()
            self.play_start_ts = self.playhead_ts

    def _highlight_event(self, idx):
        """Select and scroll to event at idx in the tree."""
        children = self.tree.get_children()
        if idx < len(children):
            item = children[idx]
            self.tree.selection_set(item)
            self.tree.see(item)

    # ── Refresh UI ───────────────────────────────────────────────────────

    def _refresh(self):
        self._update_info()
        self._draw_timeline()
        self._populate_events()
        self._update_marker_info()

    def _update_info(self):
        if not self.header:
            self.info_var.set("No file loaded")
            return
        h = self.header
        name = os.path.basename(self.file_path) if self.file_path else "untitled"
        dur = self.events[-1][0] if self.events else 0.0
        markers = sum(1 for ev in self.events if ev[1] == "m")
        self.info_var.set(
            f"{name}  |  {h.get('width', '?')}x{h.get('height', '?')}  |  "
            f"{dur:.2f}s  |  {len(self.events)} events  |  {markers} markers")

    def _populate_events(self):
        self.tree.delete(*self.tree.get_children())
        type_names = {"o": "output", "i": "input", "m": "marker", "r": "resize"}
        for ev in self.events:
            t = f"{ev[0]:.4f}"
            etype = type_names.get(ev[1], ev[1])
            data = repr(ev[2]) if len(ev[2]) > 80 else ev[2]
            tags = ()
            if ev[1] == "m":
                tags = ("marker",)
            self.tree.insert("", tk.END, values=(t, etype, data), tags=tags)
        self.tree.tag_configure("marker", foreground=COL_MARKER)

    # ── Timeline Drawing ─────────────────────────────────────────────────

    def _draw_timeline(self):
        c = self.timeline
        c.delete("all")
        w = c.winfo_width()
        h = c.winfo_height()
        if w < 10 or not self.events:
            c.create_text(w // 2, h // 2, text="Open a .cast file to begin",
                          fill=COL_SUBTEXT, font=("monospace", 11))
            return

        pad = 40
        track_y = h // 2
        track_w = w - 2 * pad
        dur = self.duration if self.duration > 0 else 1.0

        # Draw track background
        c.create_line(pad, track_y, pad + track_w, track_y,
                      fill=COL_OVERLAY, width=3)

        # Draw time labels
        num_labels = max(2, min(10, int(track_w / 80)))
        for i in range(num_labels + 1):
            t = dur * i / num_labels
            x = pad + (t / dur) * track_w
            c.create_line(x, track_y - 8, x, track_y + 8, fill=COL_OVERLAY, width=1)
            c.create_text(x, track_y + 18, text=f"{t:.1f}s",
                          fill=COL_SUBTEXT, font=("monospace", 8))

        # Draw selection region
        if self.start_marker is not None and self.end_marker is not None:
            x1 = pad + (self.start_marker / dur) * track_w
            x2 = pad + (self.end_marker / dur) * track_w
            c.create_rectangle(x1, track_y - 20, x2, track_y + 20,
                               fill=COL_SELECTION, stipple="gray25",
                               outline=COL_SELECTION, width=1)

        # Draw event ticks
        for ev in self.events:
            x = pad + (ev[0] / dur) * track_w
            if ev[1] == "m":
                c.create_line(x, track_y - 25, x, track_y + 25,
                              fill=COL_MARKER, width=2)
                c.create_text(x, track_y - 30, text=ev[2] if ev[2] else "m",
                              fill=COL_MARKER, font=("monospace", 7), anchor=tk.S)
            else:
                c.create_line(x, track_y - 6, x, track_y + 6,
                              fill=COL_EVENT_TICK, width=1)

        # Draw start/end markers
        if self.start_marker is not None:
            x = pad + (self.start_marker / dur) * track_w
            c.create_line(x, 2, x, h - 2, fill=COL_START, width=2, dash=(4, 2))
            c.create_text(x + 3, 4, text="START", anchor=tk.NW,
                          fill=COL_START, font=("monospace", 8, "bold"))

        if self.end_marker is not None:
            x = pad + (self.end_marker / dur) * track_w
            c.create_line(x, 2, x, h - 2, fill=COL_END, width=2, dash=(4, 2))
            c.create_text(x - 3, 4, text="END", anchor=tk.NE,
                          fill=COL_END, font=("monospace", 8, "bold"))

        # Draw playhead
        if self.playing or self.playhead_ts > 0:
            x = pad + (self.playhead_ts / dur) * track_w
            # Played region
            c.create_line(pad, track_y, x, track_y,
                          fill=COL_PLAYHEAD, width=3)
            # Playhead marker
            c.create_polygon(x - 5, 4, x + 5, 4, x, 12,
                             fill=COL_PLAYHEAD, outline="")
            c.create_line(x, 4, x, h - 4,
                          fill=COL_PLAYHEAD, width=2)

    # ── Timeline Interaction ─────────────────────────────────────────────

    def _ts_from_x(self, x):
        w = self.timeline.winfo_width()
        pad = 40
        track_w = w - 2 * pad
        dur = self.duration if self.duration > 0 else 1.0
        t = (x - pad) / track_w * dur
        return max(0.0, min(dur, round(t, 4)))

    def _on_timeline_click(self, event):
        if not self.events:
            return
        ts = self._ts_from_x(event.x)
        if self.marker_mode == "start":
            self.start_marker = ts
            self.marker_mode = None
            self._draw_timeline()
            self._update_marker_info()
        elif self.marker_mode == "end":
            self.end_marker = ts
            self.marker_mode = None
            if self.start_marker is not None and self.end_marker < self.start_marker:
                self.start_marker, self.end_marker = self.end_marker, self.start_marker
            self._draw_timeline()
            self._update_marker_info()
        elif not self.playing:
            # Seek: click timeline to jump to that time and show terminal state
            self._seek_to(ts)

    def _seek_to(self, ts):
        """Seek to a timestamp: render terminal up to that point, highlight event."""
        idx = 0
        for i, ev in enumerate(self.events):
            if ev[0] <= ts:
                idx = i
            else:
                break
        self.playhead_ts = ts
        self.play_event_idx = idx + 1
        self._render_term_at(idx)
        self._highlight_event(idx)
        self.play_time_var.set(f"{ts:.2f}s / {self.duration:.2f}s")
        self._draw_timeline()

    def _on_timeline_hover(self, event):
        if not self.events:
            return
        ts = self._ts_from_x(event.x)
        self.hover_var.set(f"{ts:.2f}s")
        self.hover_label.place(x=event.x + self.timeline.winfo_rootx() - self.root.winfo_rootx(),
                               y=self.timeline.winfo_rooty() - self.root.winfo_rooty() - 20)

    def _set_marker_mode(self, mode):
        if not self.events:
            messagebox.showinfo("Info", "Open a file first.")
            return
        self.marker_mode = mode
        self._update_marker_info()

    def _clear_markers(self):
        had_markers = self.start_marker is not None or self.end_marker is not None
        self.start_marker = None
        self.end_marker = None
        self.marker_mode = None
        self._draw_timeline()
        self._update_marker_info()
        if had_markers:
            self.timeline.configure(bg="#2a2a3e")
            self.root.after(150, lambda: self.timeline.configure(bg=COL_TIMELINE_BG))

    def _update_marker_info(self):
        parts = []
        if self.marker_mode == "start":
            parts.append(">> Click timeline to set START")
        elif self.marker_mode == "end":
            parts.append(">> Click timeline to set END")

        if self.start_marker is not None:
            parts.append(f"S:{self.start_marker:.2f}s")
        if self.end_marker is not None:
            parts.append(f"E:{self.end_marker:.2f}s")
        if self.start_marker is not None and self.end_marker is not None:
            sel = self.end_marker - self.start_marker
            parts.append(f"Sel:{sel:.2f}s")

        self.marker_info.set("  |  ".join(parts) if parts else "")

    # ── Require selection ────────────────────────────────────────────────

    def _require_file(self):
        if not self.header:
            messagebox.showinfo("Info", "Open a file first.")
            return False
        return True

    def _require_selection(self):
        if not self._require_file():
            return False
        if self.start_marker is None or self.end_marker is None:
            messagebox.showinfo("Info",
                                "Set both Start and End markers on the timeline first.")
            return False
        return True

    # ── Operations ───────────────────────────────────────────────────────

    def do_split(self):
        if not self._require_file():
            return
        if self.start_marker is None:
            messagebox.showinfo("Info", "Set a Start marker to define the split point.")
            return

        self.play_stop()
        split_ts = self.start_marker
        before = [ev for ev in self.events if ev[0] <= split_ts]
        after = [ev for ev in self.events if ev[0] > split_ts]

        if after:
            offset = after[0][0]
            after = [[ev[0] - offset, ev[1], ev[2]] for ev in after]

        base, ext = os.path.splitext(self.file_path or "recording.cast")
        path1 = filedialog.asksaveasfilename(
            title="Save Part 1", initialfile=f"{os.path.basename(base)}_part1{ext}",
            defaultextension=".cast",
            filetypes=[("Asciicast files", "*.cast")])
        if not path1:
            return

        path2 = filedialog.asksaveasfilename(
            title="Save Part 2", initialfile=f"{os.path.basename(base)}_part2{ext}",
            defaultextension=".cast",
            filetypes=[("Asciicast files", "*.cast")])
        if not path2:
            return

        h1 = copy.deepcopy(self.header)
        h2 = copy.deepcopy(self.header)
        update_duration(h1, before)
        update_duration(h2, after)
        write_cast(path1, h1, before)
        write_cast(path2, h2, after)
        messagebox.showinfo("Split",
                            f"Split at {split_ts:.3f}s\n"
                            f"Part 1: {len(before)} events -> {path1}\n"
                            f"Part 2: {len(after)} events -> {path2}")

    def join_files(self):
        paths = filedialog.askopenfilenames(
            title="Select cast files to join (in order)",
            filetypes=[("Asciicast files", "*.cast"), ("All files", "*.*")])
        if not paths or len(paths) < 2:
            if paths and len(paths) == 1:
                messagebox.showinfo("Info", "Select at least 2 files to join.")
            return

        gap = simpledialog.askfloat("Gap", "Gap between files (seconds):",
                                    initialvalue=0.5, minvalue=0.0,
                                    parent=self.root)
        if gap is None:
            return

        try:
            header, all_events = read_cast(paths[0])
            for path in paths[1:]:
                h, events = read_cast(path)
                header["width"] = max(header.get("width", 0), h.get("width", 0))
                header["height"] = max(header.get("height", 0), h.get("height", 0))
                offset = (all_events[-1][0] if all_events else 0.0) + gap
                for ev in events:
                    all_events.append([ev[0] + offset, ev[1], ev[2]])
        except Exception as e:
            messagebox.showerror("Error", str(e))
            return

        self.play_stop()
        self._push_undo()
        self.header = header
        self.events = all_events
        self.duration = all_events[-1][0] if all_events else 0.0
        self.file_path = self.file_path or "joined.cast"
        self.start_marker = None
        self.end_marker = None
        self._init_term_buffer()
        self._refresh()
        messagebox.showinfo("Joined",
                            f"Joined {len(paths)} files ({len(all_events)} events).\n"
                            "Use 'Save As' to write the result.")

    def do_cut(self):
        if not self._require_selection():
            return
        self.play_stop()
        self._push_undo()

        start_ts, end_ts = self.start_marker, self.end_marker
        cut_duration = end_ts - start_ts
        result = []
        for ev in self.events:
            if start_ts <= ev[0] <= end_ts:
                continue
            elif ev[0] > end_ts:
                result.append([ev[0] - cut_duration, ev[1], ev[2]])
            else:
                result.append(ev)

        removed = len(self.events) - len(result)
        self.events = result
        self.duration = result[-1][0] if result else 0.0
        self.start_marker = None
        self.end_marker = None
        self._init_term_buffer()
        self._refresh()
        messagebox.showinfo("Cut",
                            f"Cut {start_ts:.3f}s - {end_ts:.3f}s\n"
                            f"Removed {removed} events ({cut_duration:.3f}s)")

    def do_save_selection(self):
        if not self._require_selection():
            return
        self.play_stop()

        start_ts, end_ts = self.start_marker, self.end_marker
        selected = [ev for ev in self.events if start_ts <= ev[0] <= end_ts]
        if not selected:
            messagebox.showinfo("Info", "No events in the selected region.")
            return

        # Re-zero timestamps so the saved file starts at 0
        result = [[ev[0] - start_ts, ev[1], ev[2]] for ev in selected]

        base, ext = os.path.splitext(self.file_path or "recording.cast")
        path = filedialog.asksaveasfilename(
            title="Save Selection",
            initialfile=f"{os.path.basename(base)}_selection{ext}",
            defaultextension=".cast",
            filetypes=[("Asciicast files", "*.cast"), ("All files", "*.*")])
        if not path:
            return

        h = copy.deepcopy(self.header)
        update_duration(h, result)
        write_cast(path, h, result)
        messagebox.showinfo("Save Selection",
                            f"Saved {len(result)} events ({end_ts - start_ts:.3f}s)\n"
                            f"to {path}")

    def do_speed(self, factor):
        if not self._require_selection():
            return
        self.play_stop()
        self._push_undo()

        start_ts, end_ts = self.start_marker, self.end_marker
        section_duration = end_ts - start_ts
        new_section_duration = section_duration / factor
        time_shift = section_duration - new_section_duration

        result = []
        for ev in self.events:
            if ev[0] < start_ts:
                result.append(ev)
            elif ev[0] <= end_ts:
                pos = ev[0] - start_ts
                result.append([start_ts + pos / factor, ev[1], ev[2]])
            else:
                result.append([ev[0] - time_shift, ev[1], ev[2]])

        self.events = result
        self.duration = result[-1][0] if result else 0.0
        self.end_marker = start_ts + new_section_duration
        self._init_term_buffer()
        self._refresh()
        messagebox.showinfo("Speed",
                            f"Applied {factor}x speed to {start_ts:.3f}s - {end_ts:.3f}s\n"
                            f"Section: {section_duration:.3f}s -> {new_section_duration:.3f}s")

    def do_speed_custom(self):
        if not self._require_selection():
            return
        factor = simpledialog.askfloat(
            "Speed Factor",
            "Enter speed factor (e.g. 2.0 = 2x faster, 0.5 = half speed):",
            initialvalue=2.0, minvalue=0.01,
            parent=self.root)
        if factor:
            self.do_speed(factor)

    def do_add_marker(self):
        if not self._require_file():
            return
        if self.start_marker is None:
            messagebox.showinfo("Info", "Set a Start marker on the timeline to choose the position.")
            return

        label = simpledialog.askstring("Marker Label", "Enter marker label:",
                                       initialvalue="", parent=self.root)
        if label is None:
            return

        self._push_undo()
        ts = self.start_marker
        marker = [ts, "m", label]
        idx = 0
        for i, ev in enumerate(self.events):
            if ev[0] > ts:
                idx = i
                break
        else:
            idx = len(self.events)
        self.events.insert(idx, marker)
        self._refresh()
        messagebox.showinfo("Marker", f"Added marker '{label}' at {ts:.3f}s")

    def do_remove_markers(self):
        if not self._require_file():
            return
        markers = [ev for ev in self.events if ev[1] == "m"]
        if not markers:
            messagebox.showinfo("Info", "No markers in this file.")
            return

        win = tk.Toplevel(self.root)
        win.title("Remove Markers")
        win.configure(bg=COL_BG)
        win.geometry("420x350")
        win.transient(self.root)
        win.grab_set()

        ttk.Label(win, text="Select markers to remove:").pack(padx=10, pady=(10, 5))

        listbox = tk.Listbox(win, selectmode=tk.MULTIPLE, bg=COL_SURFACE,
                             fg=COL_TEXT, font=("monospace", 10),
                             selectbackground=COL_ACCENT, selectforeground=COL_BG,
                             highlightthickness=0, borderwidth=0)
        for m in markers:
            label = m[2] if m[2] else "(empty)"
            listbox.insert(tk.END, f"{m[0]:.3f}s  -  {label}")
        listbox.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        btn_frame = ttk.Frame(win)
        btn_frame.pack(pady=(5, 10))

        def remove_selected():
            sel = listbox.curselection()
            if not sel:
                messagebox.showinfo("Info", "No markers selected.", parent=win)
                return
            to_remove = {id(markers[i]) for i in sel}
            self._push_undo()
            self.events = [ev for ev in self.events
                           if not (ev[1] == "m" and id(ev) in to_remove)]
            self.duration = self.events[-1][0] if self.events else 0.0
            self._refresh()
            win.destroy()
            messagebox.showinfo("Removed", f"Removed {len(sel)} marker(s)")

        def remove_all():
            self._push_undo()
            count = sum(1 for ev in self.events if ev[1] == "m")
            self.events = [ev for ev in self.events if ev[1] != "m"]
            self.duration = self.events[-1][0] if self.events else 0.0
            self._refresh()
            win.destroy()
            messagebox.showinfo("Removed", f"Removed all {count} marker(s)")

        def select_all():
            listbox.select_set(0, tk.END)

        ttk.Button(btn_frame, text="Select All",
                   command=select_all).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_frame, text="Remove Selected", style="End.TButton",
                   command=remove_selected).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_frame, text="Remove All", style="End.TButton",
                   command=remove_all).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_frame, text="Cancel",
                   command=win.destroy).pack(side=tk.LEFT, padx=4)

    def _on_tree_right_click(self, event):
        item = self.tree.identify_row(event.y)
        if not item:
            return
        self.tree.selection_set(item)
        values = self.tree.item(item, "values")
        if values and values[1] == "marker":
            self.tree_menu.post(event.x_root, event.y_root)

    def _remove_selected_marker(self):
        sel = self.tree.selection()
        if not sel:
            return
        item = sel[0]
        idx = self.tree.index(item)
        if idx < len(self.events) and self.events[idx][1] == "m":
            self._push_undo()
            removed = self.events.pop(idx)
            label = removed[2] if removed[2] else "(empty)"
            self.duration = self.events[-1][0] if self.events else 0.0
            self._refresh()
            messagebox.showinfo("Removed", f"Removed marker '{label}' at {removed[0]:.3f}s")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    root = tk.Tk()
    AsciineditorGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
