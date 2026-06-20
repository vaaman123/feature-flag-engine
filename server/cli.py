#!/usr/bin/env python3
"""
Feature Flag Engine — Command-Line Interface
============================================
A scriptable CLI for automating flag and config management in CI/CD
pipelines, deployment scripts, or interactive terminal sessions.

Usage
─────
  python cli.py [--server URL] COMMAND [ARGS] [OPTIONS]

Commands
────────
  flags list
  flags create NAME [--enabled] [--targeting everyone|beta|pct:N|users:a,b] [--desc TEXT]
  flags on  NAME
  flags off NAME
  flags toggle NAME
  flags delete NAME

  configs list
  configs set KEY VALUE [--type string|number|boolean] [--desc TEXT]
  configs delete KEY

  evaluate [--user USER] [--beta]
  audit    [--limit N]
  export   [FILE]          (stdout if FILE omitted)
  import   FILE

Examples
────────
  python cli.py flags list
  python cli.py flags create dark_mode --targeting beta --desc "Dark theme"
  python cli.py flags on  new_checkout_flow
  python cli.py flags off new_checkout_flow
  python cli.py configs set welcome_message "Hello!" --type string
  python cli.py evaluate --user alice --beta
  python cli.py export backup.json
  python cli.py import backup.json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List

import httpx

DEFAULT_SERVER = "http://localhost:8000"

# ── Colour helpers (no deps) ──────────────────────────────────────────────────
_TTY = sys.stdout.isatty()

def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _TTY else text

def green(t):  return _c("32", t)
def red(t):    return _c("31", t)
def yellow(t): return _c("33", t)
def cyan(t):   return _c("36", t)
def bold(t):   return _c("1",  t)
def dim(t):    return _c("2",  t)


# ── HTTP client factory ───────────────────────────────────────────────────────

def _client(server: str) -> httpx.Client:
    return httpx.Client(base_url=server.rstrip("/"), timeout=10.0)


def _die(msg: str) -> None:
    print(red(f"✖  {msg}"), file=sys.stderr)
    sys.exit(1)


# ── Targeting parser ──────────────────────────────────────────────────────────

def _parse_targeting(spec: str) -> Dict[str, Any]:
    """
    Parse a targeting spec string into a TargetingConfig dict.
      everyone            → {"type": "everyone"}
      beta                → {"type": "beta_users"}
      pct:25              → {"type": "percentage", "percentage": 25.0}
      users:alice,bob     → {"type": "user_ids", "user_ids": ["alice","bob"]}
    """
    spec = spec.strip()
    if spec in ("everyone", "all"):
        return {"type": "everyone"}
    if spec in ("beta", "beta_users"):
        return {"type": "beta_users"}
    if spec.startswith("pct:"):
        try:
            pct = float(spec[4:])
        except ValueError:
            _die(f"Invalid percentage in targeting spec: {spec!r}")
        return {"type": "percentage", "percentage": pct}
    if spec.startswith("users:"):
        uids = [u.strip() for u in spec[6:].split(",") if u.strip()]
        return {"type": "user_ids", "user_ids": uids}
    _die(f"Unknown targeting spec {spec!r}. "
         "Use: everyone | beta | pct:N | users:id1,id2")


# ── Formatting helpers ────────────────────────────────────────────────────────

def _targeting_str(t: Dict) -> str:
    match t.get("type"):
        case "everyone":   return dim("Everyone")
        case "beta_users": return cyan("Beta Users")
        case "percentage": return yellow(f"{t.get('percentage', 0):.0f}% Rollout")
        case "user_ids":   return cyan(f"{len(t.get('user_ids', []))} User(s)")
        case _:            return t.get("type", "?")


def _print_flags(flags: List[Dict]) -> None:
    if not flags:
        print(dim("  (no flags)"))
        return
    w = max(len(f["name"]) for f in flags)
    for f in flags:
        status = green("ON ") if f["enabled"] else red("OFF")
        t_str  = _targeting_str(f.get("targeting", {}))
        desc   = dim(f"  {f['description']}") if f.get("description") else ""
        name_padded = f['name'] + ' ' * (w - len(f['name']))
        print(f"  [{status}]  {bold(name_padded)}  {t_str}{desc}")


def _print_configs(configs: List[Dict]) -> None:
    if not configs:
        print(dim("  (no configs)"))
        return
    w = max(len(c["key"]) for c in configs)
    for c in configs:
        type_badge = dim(f"({c['type']})")
        desc = dim(f"  {c['description']}") if c.get("description") else ""
        key_padded = c['key'] + ' ' * (w - len(c['key']))
        print(f"  {bold(key_padded)}  = {cyan(c['value'])}  {type_badge}{desc}")


# ── Subcommands ───────────────────────────────────────────────────────────────

def cmd_flags_list(client: httpx.Client) -> None:
    flags = client.get("/flags/").json()
    enabled = sum(1 for f in flags if f["enabled"])
    print(bold(f"\n  Feature Flags ({enabled}/{len(flags)} enabled)\n"))
    _print_flags(flags)
    print()


def cmd_flag_create(client: httpx.Client, name: str, enabled: bool,
                    targeting_spec: str, desc: str) -> None:
    targeting = _parse_targeting(targeting_spec)
    payload   = {"name": name, "enabled": enabled,
                 "targeting": targeting, "description": desc}
    r = client.post("/flags/", json=payload)
    if r.status_code == 201:
        f = r.json()
        status = green("ON") if f["enabled"] else red("OFF")
        print(f"  {green('✔')}  Created flag {bold(name)} [{status}]  "
              f"targeting: {_targeting_str(targeting)}")
    elif r.status_code == 409:
        _die(f"Flag '{name}' already exists.")
    else:
        _die(f"Server error {r.status_code}: {r.text}")


def _set_flag_enabled(client: httpx.Client, name: str, enabled: bool) -> None:
    flags = client.get("/flags/").json()
    flag  = next((f for f in flags if f["name"] == name), None)
    if not flag:
        _die(f"Flag '{name}' not found.")
    r = client.patch(f"/flags/{flag['id']}", json={"enabled": enabled})
    if r.status_code == 200:
        word   = green("ON") if enabled else red("OFF")
        change = green("▲ enabled") if enabled else red("▼ disabled")
        print(f"  {green('✔')}  {bold(name)} turned {word}  ({change})")
    else:
        _die(f"Server error {r.status_code}: {r.text}")


def cmd_flag_on(client: httpx.Client, name: str)     -> None: _set_flag_enabled(client, name, True)
def cmd_flag_off(client: httpx.Client, name: str)    -> None: _set_flag_enabled(client, name, False)


def cmd_flag_toggle(client: httpx.Client, name: str) -> None:
    flags = client.get("/flags/").json()
    flag  = next((f for f in flags if f["name"] == name), None)
    if not flag:
        _die(f"Flag '{name}' not found.")
    _set_flag_enabled(client, name, not flag["enabled"])


def cmd_flag_delete(client: httpx.Client, name: str) -> None:
    flags = client.get("/flags/").json()
    flag  = next((f for f in flags if f["name"] == name), None)
    if not flag:
        _die(f"Flag '{name}' not found.")
    r = client.delete(f"/flags/{flag['id']}")
    if r.status_code == 204:
        print(f"  {green('✔')}  Deleted flag {bold(name)}")
    else:
        _die(f"Server error {r.status_code}: {r.text}")


def cmd_configs_list(client: httpx.Client) -> None:
    configs = client.get("/configs/").json()
    print(bold(f"\n  Remote Configs ({len(configs)} total)\n"))
    _print_configs(configs)
    print()


def cmd_config_set(client: httpx.Client, key: str, value: str,
                   type_: str, desc: str) -> None:
    configs = client.get("/configs/").json()
    existing = next((c for c in configs if c["key"] == key), None)
    payload  = {"value": value, "type": type_, "description": desc}
    if existing:
        r = client.patch(f"/configs/{existing['id']}", json=payload)
        if r.status_code == 200:
            print(f"  {green('✔')}  Updated {bold(key)} = {cyan(value)}  "
                  f"{dim('(' + type_ + ')')}")
        else:
            _die(f"Server error {r.status_code}: {r.text}")
    else:
        r = client.post("/configs/", json={"key": key, **payload})
        if r.status_code == 201:
            print(f"  {green('✔')}  Created {bold(key)} = {cyan(value)}  "
                  f"{dim('(' + type_ + ')')}")
        else:
            _die(f"Server error {r.status_code}: {r.text}")


def cmd_config_delete(client: httpx.Client, key: str) -> None:
    configs  = client.get("/configs/").json()
    existing = next((c for c in configs if c["key"] == key), None)
    if not existing:
        _die(f"Config key '{key}' not found.")
    r = client.delete(f"/configs/{existing['id']}")
    if r.status_code == 204:
        print(f"  {green('✔')}  Deleted config {bold(key)}")
    else:
        _die(f"Server error {r.status_code}: {r.text}")


def cmd_evaluate(client: httpx.Client, user_id: str, is_beta: bool) -> None:
    payload = {"user_id": user_id, "is_beta_user": is_beta}
    r = client.post("/evaluate/", json=payload)
    if r.status_code != 200:
        _die(f"Server error {r.status_code}: {r.text}")
    result  = r.json()
    flags   = result["flags"]
    configs = result["configs"]
    print(bold(f"\n  Evaluation for user={cyan(user_id)} beta={is_beta}\n"))
    print(bold("  Flags:"))
    for name, enabled in flags.items():
        bullet = green("✓") if enabled else red("✗")
        print(f"    {bullet}  {name}")
    print(bold("\n  Configs:"))
    for key, value in configs.items():
        print(f"    {cyan(key)}  =  {value}")
    print()


def cmd_audit(client: httpx.Client, limit: int) -> None:
    r = client.get(f"/audit/?limit={limit}")
    if r.status_code != 200:
        _die(f"Server error {r.status_code}: {r.text}")
    entries = r.json()
    if not entries:
        print(dim("  (no audit entries yet)"))
        return
    print(bold(f"\n  Last {len(entries)} audit entries (oldest first)\n"))
    for e in entries:
        ts     = (e.get("ts") or "")[:19].replace("T", " ")
        action = e.get("action", "?")
        colour = {"created": green, "updated": yellow, "deleted": red}.get(action, dim)
        etype  = e.get("entity_type", "?")
        name   = e.get("entity_name", "?")
        print(f"  {dim(ts)}  {colour(f'{action:7}')}"
              f"  {dim(etype):8}  {bold(name)}")
    print()


def cmd_export(client: httpx.Client, output_path: str | None) -> None:
    flags   = client.get("/flags/").json()
    configs = client.get("/configs/").json()
    payload = {
        "version":     "1.0",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "flags":       flags,
        "configs":     configs,
    }
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    if output_path:
        with open(output_path, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
        print(f"  {green('✔')}  Exported {len(flags)} flag(s), "
              f"{len(configs)} config(s) → {bold(output_path)}")
    else:
        print(text)


def cmd_import(client: httpx.Client, input_path: str,
               overwrite: bool = False) -> None:
    try:
        with open(input_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        _die(str(exc))

    flags   = data.get("flags",   [])
    configs = data.get("configs", [])
    created = skipped = updated = 0

    for flag in flags:
        payload = {k: flag[k] for k in ("name","enabled","targeting","description") if k in flag}
        r = client.post("/flags/", json=payload)
        if r.status_code == 201:
            created += 1
        elif r.status_code == 409 and overwrite:
            existing = next((f for f in client.get("/flags/").json()
                             if f["name"] == flag["name"]), None)
            if existing:
                client.patch(f"/flags/{existing['id']}", json=payload)
                updated += 1
        else:
            skipped += 1

    for cfg in configs:
        payload = {k: cfg[k] for k in ("key","value","type","description") if k in cfg}
        r = client.post("/configs/", json=payload)
        if r.status_code == 201:
            created += 1
        elif r.status_code == 409 and overwrite:
            existing = next((c for c in client.get("/configs/").json()
                             if c["key"] == cfg["key"]), None)
            if existing:
                client.patch(f"/configs/{existing['id']}", json=payload)
                updated += 1
        else:
            skipped += 1

    print(f"  {green('✔')}  Import complete — "
          f"created {green(str(created))}, "
          f"updated {yellow(str(updated))}, "
          f"skipped {dim(str(skipped))}")


# ── Argument parser ───────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="cli.py",
        description="Feature Flag Engine — Command-Line Interface",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--server", default=DEFAULT_SERVER,
                   help=f"Server base URL (default: {DEFAULT_SERVER})")
    sub = p.add_subparsers(dest="command", required=True)

    # ── flags ──
    fl = sub.add_parser("flags", help="Manage feature flags")
    fl_sub = fl.add_subparsers(dest="flags_cmd", required=True)

    fl_sub.add_parser("list", help="List all flags")

    fc = fl_sub.add_parser("create", help="Create a new flag")
    fc.add_argument("name")
    fc.add_argument("--enabled",    action="store_true", default=False)
    fc.add_argument("--targeting",  default="everyone",
                    help="everyone | beta | pct:N | users:a,b")
    fc.add_argument("--desc",       default="")

    for cmd in ("on", "off", "toggle", "delete"):
        s = fl_sub.add_parser(cmd)
        s.add_argument("name")

    # ── configs ──
    co = sub.add_parser("configs", help="Manage remote configs")
    co_sub = co.add_subparsers(dest="configs_cmd", required=True)
    co_sub.add_parser("list", help="List all configs")

    cs = co_sub.add_parser("set", help="Create or update a config key")
    cs.add_argument("key")
    cs.add_argument("value")
    cs.add_argument("--type", default="string",
                    choices=["string", "number", "boolean"])
    cs.add_argument("--desc", default="")

    cd = co_sub.add_parser("delete", help="Delete a config key")
    cd.add_argument("key")

    # ── evaluate ──
    ev = sub.add_parser("evaluate", help="Evaluate flags for a user")
    ev.add_argument("--user", default="anonymous")
    ev.add_argument("--beta", action="store_true", default=False)

    # ── audit ──
    au = sub.add_parser("audit", help="Show audit log")
    au.add_argument("--limit", type=int, default=20)

    # ── export / import ──
    ex = sub.add_parser("export", help="Export flags+configs to JSON")
    ex.add_argument("file", nargs="?", help="Output file (default: stdout)")

    im = sub.add_parser("import", help="Import flags+configs from JSON")
    im.add_argument("file")
    im.add_argument("--overwrite", action="store_true",
                    help="Update existing items instead of skipping")

    return p


def main() -> None:
    args   = build_parser().parse_args()
    server = args.server

    with _client(server) as c:
        match args.command:
            case "flags":
                match args.flags_cmd:
                    case "list":   cmd_flags_list(c)
                    case "create": cmd_flag_create(c, args.name, args.enabled,
                                                   args.targeting, args.desc)
                    case "on":     cmd_flag_on(c, args.name)
                    case "off":    cmd_flag_off(c, args.name)
                    case "toggle": cmd_flag_toggle(c, args.name)
                    case "delete": cmd_flag_delete(c, args.name)

            case "configs":
                match args.configs_cmd:
                    case "list":   cmd_configs_list(c)
                    case "set":    cmd_config_set(c, args.key, args.value,
                                                  args.type, args.desc)
                    case "delete": cmd_config_delete(c, args.key)

            case "evaluate": cmd_evaluate(c, args.user, args.beta)
            case "audit":    cmd_audit(c, args.limit)
            case "export":   cmd_export(c, args.file)
            case "import":   cmd_import(c, args.file, args.overwrite)


if __name__ == "__main__":
    main()
