# 🚀 Feature Flag & Remote Config Engine

> **Self-hosted, lightweight alternative to LaunchDarkly & Firebase Remote Config** — built with Python (FastAPI) and Flutter.
>
> **Live Demo:** [https://feature-flag-engine-xsdf.onrender.com/dashboard](https://feature-flag-engine-xsdf.onrender.com/dashboard)
>
> **API Docs:** [https://feature-flag-engine-xsdf.onrender.com/docs](https://feature-flag-engine-xsdf.onrender.com/docs)

---

## 📋 Table of Contents

1. [Project Description](#project-description)
2. [Key Features](#key-features)
3. [Architecture](#architecture)
4. [Project Structure](#project-structure)
5. [How to Compile & Run](#how-to-compile--run)
6. [API Reference](#api-reference)
7. [TUI Keyboard Reference](#tui-keyboard-reference)
8. [Targeting Logic](#targeting-logic)
9. [Flutter SDK Usage](#flutter-sdk-usage)
10. [Assumptions & Design Decisions](#assumptions--design-decisions)
11. [Additional Features](#additional-features)
12. [Testing](#testing)
13. [Deployment](#deployment)
14. [License](#license)

---

## Project Description

Modern apps need the ability to toggle features and change settings **without releasing a new version**. Feature flags let you:

- Roll out a new checkout flow to **only beta users**
- Instantly **disable a broken feature** without an app store review
- Run **A/B experiments** by showing different pricing to 10% of users
- Change a **welcome message** or **API timeout** remotely, instantly

This project is a complete, self-hosted solution with:

| Component | Technology | Purpose |
|-----------|-----------|---------|
| **Backend Server** | Python FastAPI | REST API + WebSocket for real-time push |
| **Config Manager Frontend** | HTML5/CSS/JS Web Dashboard | Browser-based control panel to manage flags & configs |
| **Terminal UI (TUI)** | Python Textual | Keyboard-driven terminal manager (Tab, Space, Enter) |
| **Command-Line Interface** | Python CLI | Scriptable tool for CI/CD pipelines and automation |
| **Flutter Client SDK** | Dart / Flutter | Mobile SDK with WebSocket, offline cache, reactive widgets |
| **Flutter Example App** | Dart / Flutter | Fully functional demo consuming the SDK |

---

## Key Features

### 🎛️ Feature Flag Management
- **Create, toggle, edit, and delete** feature flags from any of three interfaces
- **Four targeting rules**: Everyone, Beta Users, Percentage Rollout, Specific User IDs
- **Real-time propagation**: WebSocket pushes changes to all connected clients instantly
- **Audit trail**: Every mutation logged with timestamp, action, and change details

### ⚙️ Remote Configuration
- **Typed configs**: String, Number, Boolean — values are parsed to native types
- **Live editing**: Change configs without redeploying client apps
- **Search & filter**: Find configs quickly in the dashboard

### 🔌 Client Integration (Flutter SDK)
- **3-line setup**: Initialize, check flags, read configs — that's it
- **Offline persistence**: SharedPreferences cache — app shows real data before the first network round-trip
- **Reactive widgets**: `FlagBuilder` and `ConfigBuilder` rebuild only when their specific flag/config changes
- **Exponential backoff reconnect**: Handles network interruptions gracefully with jitter
- **Client-side evaluation fallback**: Uses the same hash algorithm as the server for local flag resolution

### 🛠️ Developer Experience
- **224 passing tests** with 100% pass rate
- **Interactive Swagger docs** at `/docs` — every endpoint documented and testable
- **Docker Compose** for zero-setup local development
- **One-click Render deploy** via `render.yaml` blueprint

---

## Architecture

```
┌──────────────────────┐      REST / WebSocket      ┌──────────────────────────┐
│  Web Dashboard       │ ◄──────────────────────►   │  FastAPI Server          │
│  (HTML5/CSS/JS)      │                            │  :8000                   │
├──────────────────────┤                            │                          │
│  Terminal TUI        │ ◄──────────────────────►   │  /flags      (CRUD)      │
│  (Python Textual)    │                            │  /configs    (CRUD)      │
├──────────────────────┤                            │  /evaluate   (POST)      │
│  CLI (Scriptable)    │ ◄──────────────────────►   │  /audit      (GET)       │
│  (Python)            │                            │  /ws         (WebSocket) │
├──────────────────────┤                            │  /dashboard  (HTML)      │
│  Flutter Mobile App  │ ◄──────────────────────►   └──────────┬───────────────┘
│  (Dart SDK)          │                                       │
└──────────────────────┘                            ┌──────────▼───────────────┐
                                                    │  store.json (persistent) │
                                                    │  audit.jsonl (log)       │
                                                    └──────────────────────────┘
```

**Data flow**: Mutation → persist to disk → invalidate cache → broadcast via WebSocket → all clients update in real time. No polling, no page reload.

---

## Project Structure

```
feature-flag-engine/
├── docker-compose.yml              ← One-command startup
├── render.yaml                     ← One-click Render deploy
├── README.md
│
├── server/                         ← FastAPI backend
│   ├── main.py                     ← App entry, WebSocket /ws, /dashboard
│   ├── models.py                   ← Pydantic data models
│   ├── storage.py                  ← Thread-safe JSON persistence (coalesced writes)
│   ├── websocket_manager.py        ← Broadcast manager with initial-state cache
│   ├── audit.py                    ← Append-only JSONL audit log
│   ├── seed_data.py                ← Pre-populate 4 flags + 4 configs
│   ├── cli.py                      ← 12-command scriptable CLI
│   ├── dashboard.html              ← Web control panel (3 tabs, real-time WS)
│   ├── requirements.txt
│   ├── pytest.ini
│   ├── data/
│   │   ├── store.json              ← Persisted flags & configs
│   │   └── audit.jsonl             ← Audit trail
│   ├── routers/
│   │   ├── flags.py                ← CRUD /flags (ETag support)
│   │   ├── configs.py              ← CRUD /configs (ETag support)
│   │   ├── evaluate.py             ← POST /evaluate (targeting engine)
│   │   └── audit.py                ← GET /audit
│   └── tests/                      ← 224 tests across 9 modules
│       ├── conftest.py
│       ├── test_flags.py
│       ├── test_configs.py
│       ├── test_evaluate.py
│       ├── test_audit.py
│       ├── test_cli.py
│       ├── test_storage.py
│       ├── test_websocket.py
│       └── test_performance.py
│
├── tui/                             ← Terminal UI
│   ├── manager.py                   ← Full Textual TUI (Tab, Space, Enter, N, D, R, Q)
│   └── requirements.txt
│
└── flutter_client/                  ← Flutter SDK + Example
    ├── pubspec.yaml
    ├── README.md
    ├── lib/
    │   ├── feature_flag_flutter.dart   ← Barrel export
    │   └── src/
    │       ├── client.dart             ← FeatureFlagClient (WS, offline cache)
    │       ├── models.dart             ← Data models + targeting enums
    │       └── flag_builder.dart       ← Selective-rebuild Flutter widget
    └── example/
        ├── pubspec.yaml
        └── lib/main.dart               ← Full demo app
```

---

## How to Compile & Run

### Prerequisites

- **Python 3.10+** (tested on 3.12 and 3.14)
- **pip** (Python package manager)
- **Flutter SDK 3.10+** (only for the Flutter client)
- **Docker** (optional, for containerized setup)

---

### 🐳 Option A: Docker (Simplest)

```bash
cd feature-flag-engine
docker compose up
```

The server starts on **http://localhost:8000** with demo data pre-seeded. Open **http://localhost:8000/dashboard** for the control panel.

---

### 💻 Option B: Manual Setup

#### Step 1: Start the Backend Server

**Windows (PowerShell):**
```powershell
cd feature-flag-engine\server
pip install -r requirements.txt
python seed_data.py
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

**macOS / Linux:**
```bash
cd feature-flag-engine/server
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python3 seed_data.py
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Verify:
- **Health check**: http://localhost:8000/ → `{"status": "running"}`
- **Dashboard**: http://localhost:8000/dashboard
- **API Docs**: http://localhost:8000/docs

#### Step 2: Run the Terminal UI (separate terminal)

```bash
cd feature-flag-engine/tui
pip install -r requirements.txt
python manager.py
```

#### Step 3: Run the CLI

```bash
cd feature-flag-engine/server
python cli.py flags list              # List all flags
python cli.py configs list            # List all configs
python cli.py evaluate --user alice --beta   # Test evaluation
python cli.py flags toggle dark_mode_beta     # Toggle a flag
python cli.py audit                   # View audit log
python cli.py export backup.json      # Export all data
```

#### Step 4: Run the Flutter Example App

```bash
cd feature-flag-engine/flutter_client/example
flutter pub get
flutter run
```

> **Android emulator?** Change `kServerUrl` in `lib/main.dart` to `http://10.0.2.2:8000`.
> **iOS simulator / desktop?** Keep `http://localhost:8000`.

#### Step 5: Run Tests

```bash
cd feature-flag-engine/server
pytest tests/ -v
# Output: 224 passed ✅
```

---

## API Reference

Full interactive documentation at **http://localhost:8000/docs** (Swagger UI).

### Feature Flags

| Method | Endpoint | Description | Status Codes |
|--------|----------|-------------|--------------|
| `GET` | `/flags/` | List all flags (supports ETag/304) | 200, 304 |
| `POST` | `/flags/` | Create a new flag | 201, 409 |
| `GET` | `/flags/{id}` | Get a single flag | 200, 404 |
| `PATCH` | `/flags/{id}` | Update a flag (toggle, re-target) | 200, 404 |
| `DELETE` | `/flags/{id}` | Delete a flag | 204, 404 |

**Create flag body:**
```json
{
  "name": "new_checkout_flow",
  "enabled": true,
  "targeting": { "type": "beta_users" },
  "description": "New one-step checkout for beta testers"
}
```

### Remote Configs

| Method | Endpoint | Description | Status Codes |
|--------|----------|-------------|--------------|
| `GET` | `/configs/` | List all configs (supports ETag/304) | 200, 304 |
| `POST` | `/configs/` | Create a new config | 201, 409 |
| `GET` | `/configs/{id}` | Get a single config | 200, 404 |
| `PATCH` | `/configs/{id}` | Update a config value/type | 200, 404 |
| `DELETE` | `/configs/{id}` | Delete a config | 204, 404 |

**Create config body:**
```json
{
  "key": "welcome_message",
  "value": "Hello, World!",
  "type": "string",
  "description": "Banner text on home screen"
}
```

### Evaluation

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/evaluate` | Evaluate all flags for a given user |

**Request:**
```json
{
  "user_id": "user_42",
  "is_beta_user": true
}
```

**Response:**
```json
{
  "user_id": "user_42",
  "flags": {
    "new_checkout_flow": true,
    "dark_mode_beta": false,
    "ai_recommendations": true,
    "10pct_price_experiment": false
  },
  "configs": {
    "welcome_message": "Hello, World!",
    "max_login_attempts": 5,
    "items_per_page": 20,
    "maintenance_mode": false
  }
}
```

### WebSocket — Real-Time Updates

```
WS /ws
```

| Event | Payload | Trigger |
|-------|---------|---------|
| `initial_state` | `{flags: [...], configs: [...]}` | On connect |
| `flag_created` | Full flag object | POST /flags/ |
| `flag_updated` | Full flag object | PATCH /flags/{id} |
| `flag_deleted` | `{id: "..."}` | DELETE /flags/{id} |
| `config_created` | Full config object | POST /configs/ |
| `config_updated` | Full config object | PATCH /configs/{id} |
| `config_deleted` | `{id: "..."}` | DELETE /configs/{id} |

### Audit Log

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/audit/?limit=100` | Return last N audit entries |

---

## TUI Keyboard Reference

| Key | Action |
|-----|--------|
| `Tab` / `Shift+Tab` | Switch between Flags ↔ Configs tabs |
| `↑` / `↓` | Navigate rows |
| `Space` | Toggle selected flag ON / OFF |
| `Enter` | Edit selected item (targeting, value) |
| `N` | Create new flag or config |
| `D` | Delete selected item |
| `R` | Force-refresh from server |
| `L` | Toggle event log panel |
| `Q` | Quit |

---

## Targeting Logic

| Rule | Flag is ON when... |
|------|-------------------|
| `everyone` | `enabled: true` — all users get the flag |
| `beta_users` | SDK initialized with `isBetaUser: true` |
| `percentage` | `MD5(userId:flagName) % 100 < percentage` — deterministic bucket |
| `user_ids` | Caller's `userId` is in the explicit allow-list |

**Deterministic bucketing**: The same user always lands in the same bucket, so they never flicker between ON and OFF across sessions. Uses MD5 hash for speed (C extension in CPython) with bucket memoization capped at 50,000 entries (~3.2 MB).

---

## Flutter SDK Usage

### Quick Start (3 lines)
```dart
final client = FeatureFlagClient(serverUrl: 'http://localhost:8000', userId: 'u1');
await client.initialize();
if (client.isEnabled('dark_mode_beta')) { /* show dark theme */ }
```

### Reactive Widgets
```dart
// Rebuilds ONLY when 'new_checkout_flow' changes — not on any other flag
FlagBuilder(
  client: client,
  flagName: 'new_checkout_flow',
  builder: (context, enabled) => enabled ? NewCheckout() : OldCheckout(),
)

// Typed config widget
ConfigBuilder<int>(
  client: client,
  configKey: 'max_login_attempts',
  defaultValue: 5,
  builder: (context, value) => Text('Max attempts: $value'),
)
```

### Offline Persistence
The SDK caches the last-known flag/config snapshot to SharedPreferences. On cold start, the app shows real data before the first network round-trip completes.

---

## Assumptions & Design Decisions

1. **Single-server deployment** — The JSON file store is designed for single-instance use. For multi-node deployments, swap `storage.py` for SQLite or PostgreSQL (the storage interface is isolated in one module).

2. **Thread-safe, not process-safe** — `threading.RLock` guards all reads/writes. Multiple uvicorn workers writing to the same JSON file would conflict. Use `--workers 1` (default for development) or switch to a database.

3. **Deterministic hashing for percentage rollouts** — MD5 is used for speed (fastest hash in CPython), not security. Bucket assignment is purely functional — no cryptographic guarantees needed.

4. **WebSocket connections are ephemeral** — The server does not persist connection state. Clients re-fetch `initial_state` on reconnect and re-evaluate locally.

5. **No authentication built-in** — Designed for internal/VPN deployment. Add API keys or OAuth for public-facing deployments.

6. **Coalesced disk writes** — Mutations within a 10ms window are batched into a single atomic `os.replace()` write. This means 50 rapid toggles = 1 disk write, not 50.

7. **Audit log is append-only JSONL** — Human-readable with `tail -f data/audit.jsonl | jq .`, compatible with log rotation tools, and silently skips corrupt lines on read.

---

## Additional Features

These go beyond the core problem statement and strengthen the submission:

| Feature | Description |
|---------|-------------|
| **3 Frontend Interfaces** | Web Dashboard + Terminal TUI + Scriptable CLI — not just one |
| **ETag/304 Caching** | Saves bandwidth on repeated `/flags/` and `/configs/` requests |
| **Audit Trail** | Every mutation logged with timestamp, action, entity, and changes |
| **Export/Import** | CLI supports `export backup.json` and `import backup.json` for backup & migration |
| **WebSocket Initial-State Cache** | JSON serialized once, reused for every new connection (O(1) per connect) |
| **GZip Compression** | Responses > 1KB are automatically compressed |
| **X-Process-Time Header** | Every response includes server-side latency for monitoring |
| **Surgical TUI Updates** | TUI patches individual cells on change instead of full table rebuild (O(1) vs O(N)) |
| **Offline-First Flutter SDK** | SharedPreferences cache, exponential backoff reconnect, single-flight guard |
| **Bucket Memoization** | Deterministic hash results cached — repeated evaluate calls skip hashing entirely |
| **Toast Notifications** | Dashboard shows visual confirmation on every toggle/edit/delete |

---

## Testing

```bash
cd feature-flag-engine/server
pytest tests/ -v
```

**Results: 224 passed, 0 failed**

| Test Module | What It Covers |
|-------------|---------------|
| `test_flags.py` | CRUD operations, duplicate detection, ETag 304 |
| `test_configs.py` | CRUD operations, type validation |
| `test_evaluate.py` | All 4 targeting rules, bucket determinism, cache isolation |
| `test_audit.py` | Audit trail on create/update/delete |
| `test_cli.py` | All 12 CLI commands including export/import round-trip |
| `test_storage.py` | Thread safety, coalesced writes, atomic replace |
| `test_websocket.py` | Initial state, broadcast on mutation, reconnection |
| `test_performance.py` | ETag bandwidth savings, eval cache hit ratios, WS cache invalidation |

---

## Deployment

### Live Demo (Render)

> **https://feature-flag-engine-xsdf.onrender.com/dashboard**

Deployed via `render.yaml` blueprint — one-click from GitHub. Free tier, auto-deploys on every push.

### Self-Hosted

```bash
# Using Docker
docker compose up

# Or manually on any VPS
cd server
pip install -r requirements.txt
python seed_data.py
python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

---

## License

MIT
