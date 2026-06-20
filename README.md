# 🚀 Feature Flag & Remote Config Engine

A self-hosted, lightweight alternative to **LaunchDarkly** or **Firebase Remote Config** — built with Python (FastAPI + Textual) and Flutter.

```
┌──────────────────────────────────────────────────────────────┐
│  🚀 Feature Flag & Config Manager            12:34:56        │
├──────────────────────────────────────────────────────────────┤
│  🚩 Feature Flags  │  ⚙️  Remote Configs                     │
├──────────────────────────────────────────────────────────────┤
│  #  Name                  Status   Targeting      Updated    │
│  1  new_checkout_flow     ✅ ON    Beta Users     2024-01-15 │
│  2  dark_mode_beta        ❌ OFF   Everyone       2024-01-14 │
│  3  ai_recommendations    ✅ ON    Everyone       2024-01-15 │
│  4  10pct_price_experiment✅ ON    10% Rollout    2024-01-15 │
├──────────────────────────────────────────────────────────────┤
│  ● Connected   4 flag(s)   4 config(s)                       │
├──────────────────────────────────────────────────────────────┤
│  Space Toggle  N New  Enter Edit  D Delete  R Refresh  Q Quit│
└──────────────────────────────────────────────────────────────┘
```

---

## Architecture

```
┌────────────────────┐      REST / WebSocket      ┌──────────────────────┐
│  Python TUI        │ ◄──────────────────────►   │  FastAPI Server      │
│  (Textual)         │                            │  :8000               │
└────────────────────┘                            │                      │
                                                  │  /flags   (CRUD)     │
┌────────────────────┐      REST / WebSocket      │  /configs (CRUD)     │
│  Flutter App       │ ◄──────────────────────►   │  /evaluate           │
│  (SDK + Example)   │                            │  /ws  (live push)    │
└────────────────────┘                            └──────────┬───────────┘
                                                             │
                                                    ┌────────▼────────┐
                                                    │  store.json     │
                                                    │  (persistent)   │
                                                    └─────────────────┘
```

**Real-time flow:** Any mutation (toggle, create, delete) is persisted and
immediately broadcast to all connected WebSocket clients — both the TUI and
every Flutter instance update without a page reload or app restart.

---

## Project Structure

```
feature-flag-engine/
├── docker-compose.yml          ← one-command startup
│
├── server/                     ← FastAPI backend
│   ├── main.py                 ← app + WebSocket /ws endpoint
│   ├── models.py               ← Pydantic data models
│   ├── storage.py              ← thread-safe JSON persistence
│   ├── websocket_manager.py    ← broadcast manager
│   ├── seed_data.py            ← pre-populate example data
│   ├── requirements.txt
│   └── routers/
│       ├── flags.py            ← CRUD  /flags
│       ├── configs.py          ← CRUD  /configs
│       └── evaluate.py         ← POST  /evaluate  (targeting logic)
│
├── tui/                        ← Textual terminal manager
│   ├── manager.py              ← full TUI application
│   └── requirements.txt
│
└── flutter_client/             ← Flutter SDK + example app
    ├── pubspec.yaml
    ├── README.md
    ├── lib/
    │   ├── feature_flag_flutter.dart   ← barrel export
    │   └── src/
    │       ├── client.dart             ← FeatureFlagClient
    │       └── models.dart             ← data models + enums
    └── example/
        ├── pubspec.yaml
        └── lib/
            └── main.dart               ← demo Flutter app
```

---

## Getting Started

### Option A — Docker (recommended, zero-setup)

```bash
docker compose up
```

This starts the API server on **http://localhost:8000**, seeds example data,
and watches for file changes.

---

### Option B — Manual

#### 1. Start the API server

```bash
cd server
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python seed_data.py        # pre-populate with example flags/configs
uvicorn main:app --reload --port 8000
```

Verify: open http://localhost:8000/docs (interactive Swagger UI)

#### 2. Launch the TUI (separate terminal)

```bash
cd tui
pip install -r requirements.txt
python manager.py                          # connects to http://localhost:8000
python manager.py --server http://my-vps:8000   # custom server
```

#### 3. Run the Flutter example app

```bash
cd flutter_client/example
flutter pub get
flutter run
```

> **Android emulator?** Change `kServerUrl` in `main.dart` to
> `http://10.0.2.2:8000`.

---

## REST API Reference

Interactive docs always available at **http://localhost:8000/docs**.

### Feature Flags

| Method | Endpoint          | Description               |
|--------|-------------------|---------------------------|
| GET    | `/flags/`         | List all flags            |
| POST   | `/flags/`         | Create a flag             |
| GET    | `/flags/{id}`     | Get one flag              |
| PATCH  | `/flags/{id}`     | Update (toggle / re-target) |
| DELETE | `/flags/{id}`     | Delete a flag             |

**Create flag — example body:**
```json
{
  "name": "new_checkout_flow",
  "enabled": true,
  "targeting": {
    "type": "percentage",
    "percentage": 25
  },
  "description": "New one-step checkout"
}
```

Targeting `type` options: `everyone` · `beta_users` · `percentage` · `user_ids`

### Remote Configs

| Method | Endpoint            | Description        |
|--------|---------------------|--------------------|
| GET    | `/configs/`         | List all configs   |
| POST   | `/configs/`         | Create a config    |
| GET    | `/configs/{id}`     | Get one config     |
| PATCH  | `/configs/{id}`     | Update value/type  |
| DELETE | `/configs/{id}`     | Delete a config    |

**Create config — example body:**
```json
{
  "key": "welcome_message",
  "value": "Hello, World!",
  "type": "string",
  "description": "Home screen banner text"
}
```

Config `type` options: `string` · `number` · `boolean`

### Evaluation (used by the Flutter SDK)

```
POST /evaluate
```

```json
{
  "user_id": "user_42",
  "is_beta_user": true,
  "flag_names": null
}
```

Response:
```json
{
  "user_id": "user_42",
  "flags": {
    "new_checkout_flow":     true,
    "dark_mode_beta":        false,
    "ai_recommendations":    true,
    "10pct_price_experiment": false
  },
  "configs": {
    "welcome_message":    "Hello, World!",
    "max_login_attempts": 5,
    "items_per_page":     20,
    "maintenance_mode":   false
  }
}
```

### WebSocket

```
WS /ws
```

Connect to receive live JSON events. The server pushes `initial_state`
immediately on connect, then streams mutations in real time.

| Event            | Payload                    |
|------------------|----------------------------|
| `initial_state`  | `{flags: [...], configs: [...]}` |
| `flag_created`   | full flag object           |
| `flag_updated`   | full flag object           |
| `flag_deleted`   | `{id: "..."}`              |
| `config_created` | full config object         |
| `config_updated` | full config object         |
| `config_deleted` | `{id: "..."}`              |

---

## TUI Keyboard Reference

| Key         | Action                                 |
|-------------|----------------------------------------|
| `Tab`       | Switch between Flags / Configs tabs    |
| `↑` / `↓`  | Navigate rows                          |
| `Space`     | Toggle selected flag ON / OFF          |
| `Enter`     | Edit targeting rule / config value     |
| `N`         | Create new flag or config              |
| `D`         | Delete selected item                   |
| `R`         | Force-refresh from server              |
| `L`         | Toggle event log panel                 |
| `Q`         | Quit                                   |

---

## Targeting Logic

| Rule         | When is the flag ON?                                              |
|--------------|-------------------------------------------------------------------|
| `everyone`   | Always (when `enabled: true`)                                     |
| `beta_users` | Only when the SDK is initialised with `isBetaUser: true`          |
| `percentage` | Deterministic bucket: `MD5(userId:flagName) mod 100 ≤ percentage` |
| `user_ids`   | Only when the caller's `userId` is in the explicit allow-list     |

Percentage rollouts are **deterministic** — the same user always gets the same
bucket, so they never flicker between ON and OFF across sessions.

---

## Flutter SDK — Advanced Usage

### Provide the client app-wide

```dart
// main.dart
await client.initialize();
runApp(FlagClientProvider(client: client, child: const MyApp()));

// any widget
final client = FlagClientProvider.of(context);
```

### Reactive rebuild with StreamBuilder

```dart
StreamBuilder<FlagSnapshot>(
  stream: client.snapshotStream,
  initialData: client.snapshot,
  builder: (context, _) {
    return client.isEnabled('feature_x')
        ? const FeatureXWidget()
        : const FallbackWidget();
  },
)
```

### Typed remote configs

```dart
final welcome  = client.getConfig<String>('welcome_message', 'Hi!');
final maxTries = client.getConfig<int>('max_login_attempts', 3);
final darkMode = client.getConfig<bool>('maintenance_mode', false);
```

---

## Design Decisions

- **JSON file storage** — zero external dependencies; drop-in SQLite upgrade
  path if you need concurrent writes at scale.
- **Thread-safe writes** — Python `RLock` guards every read/write cycle.
- **Deterministic percentage rollouts** — MD5 hash of `(userId, flagName)`
  ensures stable assignment without a database.
- **WebSocket-first updates** — mutations are persisted _then_ broadcast, so
  clients never see stale state.
- **Client-side evaluation fallback** — the Flutter SDK can re-evaluate from
  the `initial_state` push using the same hash logic as the server, reducing
  round-trips for percentage/everyone flags.

---

## License

MIT
