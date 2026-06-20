# feature_flag_flutter

A Flutter SDK for the self-hosted **Feature Flag & Remote Config Engine**.

## Installation

Add to your `pubspec.yaml`:

```yaml
dependencies:
  feature_flag_flutter:
    path: ../flutter_client   # local path, or publish to pub.dev
  http: ^1.2.0
  web_socket_channel: ^2.4.0
```

## Quick Start

```dart
import 'package:feature_flag_flutter/feature_flag_flutter.dart';

// 1. Create and initialise the client (call once, e.g. in main())
final client = FeatureFlagClient(
  serverUrl:  'http://localhost:8000',
  userId:     'user_42',
  isBetaUser: true,
);
await client.initialize();

// 2. Check a feature flag
if (client.isEnabled('new_checkout_flow')) {
  showExpressCheckout();
}

// 3. Read a remote config (typed)
final msg     = client.getConfig<String>('welcome_message', 'Hello!');
final maxTries = client.getConfig<int>('max_login_attempts', 5);

// 4. React to live changes (WebSocket push)
client.snapshotStream.listen((snapshot) {
  setState(() {});     // rebuild when any flag or config changes
});

// 5. Clean up
client.dispose();
```

## StreamBuilder Pattern

```dart
StreamBuilder<FlagSnapshot>(
  stream: client.snapshotStream,
  initialData: client.snapshot,
  builder: (context, _) {
    final darkMode = client.isEnabled('dark_mode_beta');
    return darkMode ? DarkWidget() : LightWidget();
  },
)
```

## Targeting Types

| Server setting   | Behaviour                                      |
|------------------|------------------------------------------------|
| `everyone`       | Flag is ON for all users when enabled          |
| `beta_users`     | ON only when `isBetaUser: true`                |
| `percentage`     | Deterministic bucket via `hash(userId:name)`   |
| `user_ids`       | ON only for explicitly listed user IDs         |

## API Reference

| Method | Description |
|--------|-------------|
| `initialize()` | Fetch initial state & open WebSocket |
| `isEnabled(name, {defaultValue})` | Returns `bool` for a flag |
| `getConfig<T>(key, defaultValue)` | Returns typed config value |
| `refresh()` | Force re-fetch from `/evaluate` |
| `snapshotStream` | Broadcast stream of `FlagSnapshot` |
| `snapshot` | Current synchronous snapshot |
| `dispose()` | Release WebSocket + stream resources |
