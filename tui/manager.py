"""
Feature Flag & Config Manager — Terminal UI
============================================
Keyboard shortcuts
  Tab / Shift+Tab  Switch between Flags ↔ Configs tabs
  ↑ / ↓           Navigate rows
  Space            Toggle selected flag ON / OFF
  Enter            Edit selected item
  N                Create a new flag / config
  D                Delete selected item
  R                Force-refresh from server
  L                Toggle the event log panel
  Q                Quit

Optimisations over previous version
────────────────────────────────────
Surgical table updates
  Previous: every WebSocket event called table.clear() then rebuilt all N
  rows from scratch — O(N) work, cursor reset, full flicker on every toggle.

  Now:
    flag_updated  → update_cell() patches only the 4 cells that can change
                    (Status, Targeting, Description, Updated).  O(1) work,
                    cursor stays exactly where it is.
    flag_created  → add_row() appends one row.  O(1).
    flag_deleted  → remove_row() drops one row, then O(N) renumber pass
                    (rare — deletions are infrequent).
    initial_state → full rebuild (only on first connect / reconnect).
    config_*      → same pattern as flags.

  This matters most in production where a TUI operator may have hundreds of
  flags loaded and is rapidly toggling flags during an incident.

Column key scheme
  Explicit string keys are passed to add_column() so update_cell() can
  reference columns by name instead of fragile positional indexes.

Run:
  python manager.py [--server http://localhost:8000]
"""
from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime
from typing import Optional

import httpx
import websockets
from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import (
    Button, DataTable, Footer, Header,
    Input, Label, Log, Select,
    TabbedContent, TabPane,
)

DEFAULT_SERVER = "http://localhost:8000"

TARGETING_OPTIONS: list[tuple[str, str]] = [
    ("Everyone",           "everyone"),
    ("Beta Users Only",    "beta_users"),
    ("Percentage Rollout", "percentage"),
    ("Specific User IDs",  "user_ids"),
]
CONFIG_TYPE_OPTIONS: list[tuple[str, str]] = [
    ("String",  "string"),
    ("Number",  "number"),
    ("Boolean", "boolean"),
]

# ── Helpers ───────────────────────────────────────────────────────────────────

def _select_value(widget: Select, default: str = "") -> str:
    v = widget.value
    return default if v is Select.BLANK else str(v)


def _targeting_label(t: dict) -> str:
    match t.get("type", "everyone"):
        case "everyone":   return "Everyone"
        case "beta_users": return "Beta Users"
        case "percentage": return f"{t.get('percentage', 0):.0f}% Rollout"
        case "user_ids":   return f"{len(t.get('user_ids', []))} User(s)"
        case other:        return other


def _status_text(enabled: bool) -> Text:
    return (Text("✅  ON ", style="bold green") if enabled
            else Text("❌  OFF", style="bold red"))


# ══════════════════════════════════════════════════════════════════════════════
# Modal screens
# ══════════════════════════════════════════════════════════════════════════════

class FlagModal(ModalScreen):
    DEFAULT_CSS = """
    FlagModal { align: center middle; }
    FlagModal > Container {
        width: 64; height: auto; max-height: 90%;
        border: double $accent; background: $surface; padding: 1 2 2 2;
    }
    FlagModal .modal-title { text-align: center; text-style: bold; color: $accent; margin-bottom: 1; }
    FlagModal .field-label { color: $text-muted; margin-top: 1; }
    FlagModal .btn-row     { margin-top: 2; align: center middle; }
    FlagModal Button       { margin: 0 1; }
    """

    def __init__(self, flag: Optional[dict] = None) -> None:
        super().__init__()
        self._flag = flag
        self._edit = flag is not None

    def compose(self) -> ComposeResult:
        flag     = self._flag or {}
        targeting = flag.get("targeting", {})
        title = f"✦  Edit Flag: {flag['name']}" if self._edit else "✦  Create Feature Flag"
        with Container():
            yield Label(title, classes="modal-title")
            if not self._edit:
                yield Label("Flag Name  *", classes="field-label")
                yield Input(placeholder="e.g. new_checkout_flow", id="name")
            yield Label("Description", classes="field-label")
            yield Input(value=flag.get("description", ""),
                        placeholder="Optional description", id="description")
            yield Label("Targeting Rule", classes="field-label")
            yield Select(TARGETING_OPTIONS,
                         value=targeting.get("type", "everyone"),
                         id="targeting_type")
            yield Label("Percentage  (0 – 100)", classes="field-label")
            pct = str(targeting.get("percentage", "")) if targeting.get("percentage") is not None else ""
            yield Input(value=pct, placeholder="e.g. 10", id="percentage",
                        disabled=targeting.get("type") != "percentage")
            yield Label("User IDs  (comma-separated)", classes="field-label")
            uids = ", ".join(targeting.get("user_ids", []))
            yield Input(value=uids, placeholder="user_a, user_b", id="user_ids",
                        disabled=targeting.get("type") != "user_ids")
            with Horizontal(classes="btn-row"):
                yield Button("Save" if self._edit else "Create",
                             variant="success", id="submit")
                yield Button("Cancel", variant="default", id="cancel")

    @on(Select.Changed, "#targeting_type")
    def _on_targeting_change(self, event: Select.Changed) -> None:
        val = _select_value(self.query_one("#targeting_type", Select), "everyone")
        self.query_one("#percentage", Input).disabled = val != "percentage"
        self.query_one("#user_ids",   Input).disabled = val != "user_ids"

    @on(Button.Pressed, "#submit")
    def _submit(self) -> None:
        name_widgets = self.query("#name")
        if name_widgets:
            name = name_widgets.first(Input).value.strip()
            if not name:
                self.notify("Flag name is required!", severity="error"); return
        else:
            name = None
        t_type  = _select_value(self.query_one("#targeting_type", Select), "everyone")
        desc    = self.query_one("#description", Input).value.strip()
        pct_str = self.query_one("#percentage",  Input).value.strip()
        uid_str = self.query_one("#user_ids",    Input).value.strip()
        targeting: dict = {"type": t_type}
        if t_type == "percentage":
            try:
                targeting["percentage"] = float(pct_str)
            except ValueError:
                self.notify("Percentage must be a number.", severity="error"); return
        elif t_type == "user_ids":
            targeting["user_ids"] = [u.strip() for u in uid_str.split(",") if u.strip()]
        result: dict = {"description": desc, "targeting": targeting}
        if name is not None:
            result["name"]    = name
            result["enabled"] = False
        self.dismiss(result)

    @on(Button.Pressed, "#cancel")
    def _cancel(self) -> None:
        self.dismiss(None)


class ConfigModal(ModalScreen):
    DEFAULT_CSS = """
    ConfigModal { align: center middle; }
    ConfigModal > Container {
        width: 60; height: auto;
        border: double $success; background: $surface; padding: 1 2 2 2;
    }
    ConfigModal .modal-title { text-align: center; text-style: bold; color: $success; margin-bottom: 1; }
    ConfigModal .field-label { color: $text-muted; margin-top: 1; }
    ConfigModal .btn-row     { margin-top: 2; align: center middle; }
    ConfigModal Button       { margin: 0 1; }
    """

    def __init__(self, config: Optional[dict] = None) -> None:
        super().__init__()
        self._config = config
        self._edit   = config is not None

    def compose(self) -> ComposeResult:
        cfg   = self._config or {}
        title = f"✦  Edit Config: {cfg['key']}" if self._edit else "✦  Create Remote Config"
        with Container():
            yield Label(title, classes="modal-title")
            if not self._edit:
                yield Label("Key  *", classes="field-label")
                yield Input(placeholder="e.g. welcome_message", id="key")
            yield Label("Value  *", classes="field-label")
            yield Input(value=cfg.get("value", ""),
                        placeholder="e.g. Hello, World!", id="value")
            yield Label("Type", classes="field-label")
            yield Select(CONFIG_TYPE_OPTIONS,
                         value=cfg.get("type", "string"), id="type")
            yield Label("Description", classes="field-label")
            yield Input(value=cfg.get("description", ""),
                        placeholder="Optional description", id="description")
            with Horizontal(classes="btn-row"):
                yield Button("Save" if self._edit else "Create",
                             variant="success", id="submit")
                yield Button("Cancel", variant="default", id="cancel")

    @on(Button.Pressed, "#submit")
    def _submit(self) -> None:
        value = self.query_one("#value", Input).value.strip()
        if not value:
            self.notify("Value is required!", severity="error"); return
        result: dict = {
            "value":       value,
            "type":        _select_value(self.query_one("#type", Select), "string"),
            "description": self.query_one("#description", Input).value.strip(),
        }
        key_widgets = self.query("#key")
        if key_widgets:
            key = key_widgets.first(Input).value.strip()
            if not key:
                self.notify("Key is required!", severity="error"); return
            result["key"] = key
        self.dismiss(result)

    @on(Button.Pressed, "#cancel")
    def _cancel(self) -> None:
        self.dismiss(None)


# ══════════════════════════════════════════════════════════════════════════════
# Main App
# ══════════════════════════════════════════════════════════════════════════════

class FlagManagerApp(App):
    """🚀 Feature Flag & Config Manager — Terminal UI."""

    TITLE     = "Feature Flag & Config Manager"
    SUB_TITLE = "○  Connecting…"

    CSS = """
    Screen { background: $background; }
    TabbedContent { height: 1fr; }
    TabPane       { padding: 0 1; }
    DataTable     { height: 1fr; }
    #log_panel {
        height: 8;
        border-top: solid $primary-darken-2;
        background: $surface-darken-1;
    }
    """

    BINDINGS = [
        Binding("space", "toggle_flag", "Toggle",  show=True),
        Binding("n",     "new_item",    "New",     show=True),
        Binding("enter", "edit_item",   "Edit",    show=True),
        Binding("d",     "delete_item", "Delete",  show=True),
        Binding("r",     "refresh",     "Refresh", show=True),
        Binding("l",     "toggle_log",  "Log",     show=True),
        Binding("q",     "quit",        "Quit",    show=True),
    ]

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def __init__(self, server_url: str = DEFAULT_SERVER) -> None:
        super().__init__()
        self.server_url    = server_url.rstrip("/")
        self.ws_url        = self.server_url.replace("http", "ws") + "/ws"
        self._flags:   list[dict] = []
        self._configs: list[dict] = []
        self._ws_connected = False
        self._log_visible  = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with TabbedContent(id="tabs"):
            with TabPane("🚩  Feature Flags", id="flags_pane"):
                yield DataTable(id="flags_table",
                                cursor_type="row", zebra_stripes=True)
            with TabPane("⚙️   Remote Configs", id="configs_pane"):
                yield DataTable(id="configs_table",
                                cursor_type="row", zebra_stripes=True)
        yield Log(id="log_panel", highlight=True, max_lines=200)
        yield Footer()

    def on_mount(self) -> None:
        # ── Flags table — explicit column keys enable surgical cell updates
        ft = self.query_one("#flags_table", DataTable)
        ft.add_column("#",              key="num")
        ft.add_column("Name",           key="name")
        ft.add_column("Status",         key="status")
        ft.add_column("Targeting Rule", key="targeting")
        ft.add_column("Description",    key="desc")
        ft.add_column("Updated",        key="updated")

        # ── Configs table
        ct = self.query_one("#configs_table", DataTable)
        ct.add_column("#",           key="num")
        ct.add_column("Key",         key="key")
        ct.add_column("Value",       key="value")
        ct.add_column("Type",        key="type")
        ct.add_column("Description", key="desc")
        ct.add_column("Updated",     key="updated")

        self.query_one("#log_panel").display = False
        self.load_data()
        self.ws_listener()

    # ── Workers ───────────────────────────────────────────────────────────────

    @work(exclusive=False, name="load_data")
    async def load_data(self) -> None:
        try:
            async with httpx.AsyncClient(timeout=5.0) as c:
                f_resp = await c.get(f"{self.server_url}/flags/")
                c_resp = await c.get(f"{self.server_url}/configs/")
                f_resp.raise_for_status(); c_resp.raise_for_status()
                self._flags   = f_resp.json()
                self._configs = c_resp.json()
                self._rebuild_flags_table()
                self._rebuild_configs_table()
                self._log(f"Loaded {len(self._flags)} flag(s), "
                          f"{len(self._configs)} config(s).")
        except httpx.ConnectError:
            self._log(f"Cannot reach {self.server_url}", level="ERROR")
            self.notify(f"Server unreachable: {self.server_url}",
                        severity="error", timeout=8)
        except Exception as exc:
            self._log(f"Load error: {exc}", level="ERROR")

    @work(exclusive=True, name="ws_listener", exit_on_error=False)
    async def ws_listener(self) -> None:
        while True:
            try:
                async with websockets.connect(self.ws_url) as ws:
                    self._ws_connected = True
                    self._update_subtitle()
                    self._log("WebSocket connected ✓")
                    async for raw in ws:
                        self._handle_ws_message(json.loads(raw))
            except Exception as exc:
                self._ws_connected = False
                self._update_subtitle()
                self._log(f"WS disconnected: {exc} — retrying in 3 s…",
                          level="WARN")
                await asyncio.sleep(3)

    # ── WebSocket handler (surgical updates) ──────────────────────────────────

    def _handle_ws_message(self, msg: dict) -> None:
        event = msg.get("event", "")
        data  = msg.get("data", {})

        match event:
            # ── Full rebuild (connect / reconnect only) ────────────────────
            case "initial_state":
                self._flags   = data.get("flags",   [])
                self._configs = data.get("configs", [])
                self._rebuild_flags_table()
                self._rebuild_configs_table()

            # ── Surgical flag updates ──────────────────────────────────────
            case "flag_updated":
                idx = next((i for i, f in enumerate(self._flags)
                            if f["id"] == data["id"]), None)
                if idx is not None:
                    self._flags[idx] = data
                    self._patch_flag_row(data)          # O(1) cell updates
                else:
                    self._flags.append(data)
                    self._rebuild_flags_table()

            case "flag_created":
                self._flags.append(data)
                self._append_flag_row(data, len(self._flags))   # O(1)

            case "flag_deleted":
                self._flags = [f for f in self._flags if f["id"] != data["id"]]
                try:
                    self.query_one("#flags_table", DataTable).remove_row(data["id"])
                    self._renumber_flags()              # O(N) but rare
                except Exception:
                    self._rebuild_flags_table()

            # ── Surgical config updates ────────────────────────────────────
            case "config_updated":
                idx = next((i for i, c in enumerate(self._configs)
                            if c["id"] == data["id"]), None)
                if idx is not None:
                    self._configs[idx] = data
                    self._patch_config_row(data)        # O(1) cell updates
                else:
                    self._configs.append(data)
                    self._rebuild_configs_table()

            case "config_created":
                self._configs.append(data)
                self._append_config_row(data, len(self._configs))

            case "config_deleted":
                self._configs = [c for c in self._configs if c["id"] != data["id"]]
                try:
                    self.query_one("#configs_table", DataTable).remove_row(data["id"])
                    self._renumber_configs()
                except Exception:
                    self._rebuild_configs_table()

        self._update_subtitle()
        self._log(f"← {event}")

    # ── Full rebuild (initial_state / reconnect) ───────────────────────────

    def _rebuild_flags_table(self) -> None:
        table = self.query_one("#flags_table", DataTable)
        cur   = table.cursor_row
        table.clear()
        for idx, flag in enumerate(self._flags, 1):
            self._append_flag_row(flag, idx)
        if self._flags:
            table.move_cursor(row=min(cur, len(self._flags) - 1))

    def _rebuild_configs_table(self) -> None:
        table = self.query_one("#configs_table", DataTable)
        cur   = table.cursor_row
        table.clear()
        for idx, cfg in enumerate(self._configs, 1):
            self._append_config_row(cfg, idx)
        if self._configs:
            table.move_cursor(row=min(cur, len(self._configs) - 1))

    # ── Append helpers (used by both rebuild and flag_created) ───────────────

    def _append_flag_row(self, flag: dict, num: int) -> None:
        table = self.query_one("#flags_table", DataTable)
        t = flag.get("targeting", {})
        table.add_row(
            str(num),
            flag["name"],
            _status_text(flag.get("enabled", False)),
            _targeting_label(t),
            (flag.get("description") or "")[:45],
            (flag.get("updated_at")  or "")[:10],
            key=flag["id"],
        )

    def _append_config_row(self, cfg: dict, num: int) -> None:
        table = self.query_one("#configs_table", DataTable)
        val = str(cfg.get("value", ""))
        table.add_row(
            str(num),
            cfg["key"],
            val[:50] + ("…" if len(val) > 50 else ""),
            cfg.get("type", "string"),
            (cfg.get("description") or "")[:45],
            (cfg.get("updated_at")  or "")[:10],
            key=cfg["id"],
        )

    # ── Surgical cell-patch helpers (O(1) — only changed cells) ─────────────

    def _patch_flag_row(self, flag: dict) -> None:
        """Update only the 4 mutable cells in an existing flag row."""
        table = self.query_one("#flags_table", DataTable)
        fid   = flag["id"]
        t     = flag.get("targeting", {})
        try:
            table.update_cell(fid, "status",    _status_text(flag.get("enabled", False)), update_width=False)
            table.update_cell(fid, "targeting", _targeting_label(t),                      update_width=False)
            table.update_cell(fid, "desc",      (flag.get("description") or "")[:45],     update_width=False)
            table.update_cell(fid, "updated",   (flag.get("updated_at")  or "")[:10],     update_width=False)
        except Exception:
            self._rebuild_flags_table()

    def _patch_config_row(self, cfg: dict) -> None:
        """Update only the 3 mutable cells in an existing config row."""
        table = self.query_one("#configs_table", DataTable)
        cid   = cfg["id"]
        val   = str(cfg.get("value", ""))
        try:
            table.update_cell(cid, "value",   val[:50] + ("…" if len(val) > 50 else ""), update_width=False)
            table.update_cell(cid, "type",    cfg.get("type", "string"),                  update_width=False)
            table.update_cell(cid, "desc",    (cfg.get("description") or "")[:45],        update_width=False)
            table.update_cell(cid, "updated", (cfg.get("updated_at")  or "")[:10],        update_width=False)
        except Exception:
            self._rebuild_configs_table()

    # ── Renumber after a delete (O(N), fires only on deletions) ──────────────

    def _renumber_flags(self) -> None:
        table = self.query_one("#flags_table", DataTable)
        for idx, flag in enumerate(self._flags, 1):
            try:
                table.update_cell(flag["id"], "num", str(idx), update_width=False)
            except Exception:
                pass

    def _renumber_configs(self) -> None:
        table = self.query_one("#configs_table", DataTable)
        for idx, cfg in enumerate(self._configs, 1):
            try:
                table.update_cell(cfg["id"], "num", str(idx), update_width=False)
            except Exception:
                pass

    # ── UI helpers ────────────────────────────────────────────────────────────

    def _log(self, message: str, level: str = "INFO") -> None:
        ts     = datetime.now().strftime("%H:%M:%S")
        colour = {"INFO": "cyan", "WARN": "yellow", "ERROR": "red"}.get(level, "white")
        self.query_one("#log_panel", Log).write_line(
            f"[{ts}] [{colour}]{level}[/{colour}]  {message}"
        )

    def _update_subtitle(self) -> None:
        if self._ws_connected:
            self.sub_title = (f"●  Connected   "
                              f"{len(self._flags)} flag(s)   "
                              f"{len(self._configs)} config(s)")
        else:
            self.sub_title = "○  Disconnected"

    def _active_tab(self) -> str:
        return str(self.query_one("#tabs", TabbedContent).active)

    def _selected_flag(self) -> Optional[dict]:
        table = self.query_one("#flags_table", DataTable)
        idx   = table.cursor_row
        return self._flags[idx] if 0 <= idx < len(self._flags) else None

    def _selected_config(self) -> Optional[dict]:
        table = self.query_one("#configs_table", DataTable)
        idx   = table.cursor_row
        return self._configs[idx] if 0 <= idx < len(self._configs) else None

    # ── Actions ───────────────────────────────────────────────────────────────

    async def action_toggle_flag(self) -> None:
        if self._active_tab() != "flags_pane":
            return
        flag = self._selected_flag()
        if not flag:
            self.notify("No flag selected.", severity="warning"); return
        new_state = not flag.get("enabled", False)
        try:
            async with httpx.AsyncClient(timeout=5.0) as c:
                r = await c.patch(f"{self.server_url}/flags/{flag['id']}",
                                  json={"enabled": new_state})
                if r.status_code == 200:
                    self.notify(f"'{flag['name']}' → {'ON' if new_state else 'OFF'}.",
                                severity="information")
                else:
                    self.notify(f"Server error {r.status_code}", severity="error")
        except Exception as exc:
            self.notify(str(exc), severity="error")

    async def action_new_item(self) -> None:
        tab = self._active_tab()
        if tab == "flags_pane":
            result = await self.push_screen_wait(FlagModal())
            if result:
                try:
                    async with httpx.AsyncClient(timeout=5.0) as c:
                        r = await c.post(f"{self.server_url}/flags/", json=result)
                        if r.status_code == 201:
                            self.notify(f"Flag '{result['name']}' created!", severity="information")
                        elif r.status_code == 409:
                            self.notify(f"'{result['name']}' already exists.", severity="error")
                        else:
                            self.notify(f"Error {r.status_code}", severity="error")
                except Exception as exc:
                    self.notify(str(exc), severity="error")
        elif tab == "configs_pane":
            result = await self.push_screen_wait(ConfigModal())
            if result:
                try:
                    async with httpx.AsyncClient(timeout=5.0) as c:
                        r = await c.post(f"{self.server_url}/configs/", json=result)
                        if r.status_code == 201:
                            self.notify(f"Config '{result['key']}' created!", severity="information")
                        elif r.status_code == 409:
                            self.notify(f"Key '{result['key']}' already exists.", severity="error")
                        else:
                            self.notify(f"Error {r.status_code}", severity="error")
                except Exception as exc:
                    self.notify(str(exc), severity="error")

    async def action_edit_item(self) -> None:
        tab = self._active_tab()
        if tab == "flags_pane":
            flag = self._selected_flag()
            if not flag:
                self.notify("No flag selected.", severity="warning"); return
            result = await self.push_screen_wait(FlagModal(flag))
            if result:
                try:
                    async with httpx.AsyncClient(timeout=5.0) as c:
                        r = await c.patch(f"{self.server_url}/flags/{flag['id']}", json=result)
                        if r.status_code != 200:
                            self.notify(f"Error {r.status_code}", severity="error")
                except Exception as exc:
                    self.notify(str(exc), severity="error")
        elif tab == "configs_pane":
            cfg = self._selected_config()
            if not cfg:
                self.notify("No config selected.", severity="warning"); return
            result = await self.push_screen_wait(ConfigModal(cfg))
            if result:
                try:
                    async with httpx.AsyncClient(timeout=5.0) as c:
                        r = await c.patch(f"{self.server_url}/configs/{cfg['id']}", json=result)
                        if r.status_code != 200:
                            self.notify(f"Error {r.status_code}", severity="error")
                except Exception as exc:
                    self.notify(str(exc), severity="error")

    async def action_delete_item(self) -> None:
        tab = self._active_tab()
        if tab == "flags_pane":
            flag = self._selected_flag()
            if not flag:
                self.notify("No flag selected.", severity="warning"); return
            try:
                async with httpx.AsyncClient(timeout=5.0) as c:
                    r = await c.delete(f"{self.server_url}/flags/{flag['id']}")
                    if r.status_code != 204:
                        self.notify(f"Error {r.status_code}", severity="error")
            except Exception as exc:
                self.notify(str(exc), severity="error")
        elif tab == "configs_pane":
            cfg = self._selected_config()
            if not cfg:
                self.notify("No config selected.", severity="warning"); return
            try:
                async with httpx.AsyncClient(timeout=5.0) as c:
                    r = await c.delete(f"{self.server_url}/configs/{cfg['id']}")
                    if r.status_code != 204:
                        self.notify(f"Error {r.status_code}", severity="error")
            except Exception as exc:
                self.notify(str(exc), severity="error")

    async def action_refresh(self) -> None:
        self._log("Manual refresh…")
        self.load_data()
        self.notify("Refreshed!", severity="information")

    def action_toggle_log(self) -> None:
        self._log_visible = not self._log_visible
        self.query_one("#log_panel").display = self._log_visible

    def action_quit(self) -> None:
        self.exit()


# ── Entry-point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Feature Flag Manager — TUI")
    parser.add_argument("--server", default=DEFAULT_SERVER, metavar="URL",
                        help=f"Server base URL (default: {DEFAULT_SERVER})")
    FlagManagerApp(server_url=parser.parse_args().server).run()
