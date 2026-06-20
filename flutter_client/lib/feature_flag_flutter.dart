/// Feature Flag Flutter SDK
///
/// ```dart
/// import 'package:feature_flag_flutter/feature_flag_flutter.dart';
///
/// // Initialise once
/// final client = FeatureFlagClient(serverUrl: 'http://localhost:8000', userId: 'u1');
/// await client.initialize();
///
/// // Check a flag
/// client.isEnabled('dark_mode_beta');
///
/// // Get a typed config
/// client.getConfig<String>('welcome_message', 'Hello!');
///
/// // Reactive widget (rebuilds only when this flag changes)
/// FlagBuilder(client: client, flagName: 'new_feature', builder: (ctx, on) => ...);
///
/// // Reactive config widget
/// ConfigBuilder<int>(client: client, configKey: 'page_size', defaultValue: 20,
///                    builder: (ctx, size) => ...);
/// ```
library feature_flag_flutter;

export 'src/client.dart';
export 'src/models.dart';
export 'src/flag_builder.dart';
