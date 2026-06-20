/// FlagBuilder — a Flutter widget that rebuilds only when one specific
/// feature flag changes, not on any flag or config update.
///
/// Why this matters
/// ────────────────
/// Using StreamBuilder<FlagSnapshot> at the root level means every widget
/// that listens to snapshotStream rebuilds whenever *any* flag or config
/// changes — even ones it doesn't care about.
///
/// FlagBuilder subscribes to the same stream but compares only the value
/// of the flag it cares about.  setState is called only when that specific
/// boolean flips, making rebuilds O(1) in flag count.
///
/// Usage
/// ─────
/// ```dart
/// FlagBuilder(
///   client:    client,
///   flagName:  'dark_mode_beta',
///   builder:   (context, enabled) => enabled
///       ? const DarkThemeWidget()
///       : const LightThemeWidget(),
/// )
/// ```
///
/// Or with a default value if the flag hasn't loaded yet:
/// ```dart
/// FlagBuilder(
///   client:       client,
///   flagName:     'new_checkout_flow',
///   defaultValue: false,
///   builder:      (context, enabled) => CheckoutWidget(newFlow: enabled),
/// )
/// ```
library;

import 'dart:async';
import 'package:flutter/widgets.dart';

import 'client.dart';
import 'models.dart';

/// A widget that rebuilds only when [flagName] changes value.
///
/// More efficient than wrapping an entire sub-tree in
/// `StreamBuilder<FlagSnapshot>` when you only care about one flag.
class FlagBuilder extends StatefulWidget {
  const FlagBuilder({
    super.key,
    required this.client,
    required this.flagName,
    required this.builder,
    this.defaultValue = false,
  });

  /// The [FeatureFlagClient] providing live flag state.
  final FeatureFlagClient client;

  /// The name of the flag to watch.
  final String flagName;

  /// Called every time [flagName] changes (or on first build).
  /// [enabled] is the current value of the flag.
  final Widget Function(BuildContext context, bool enabled) builder;

  /// Returned while the flag is unknown (before [initialize] completes
  /// or if the flag name doesn't exist on the server).
  final bool defaultValue;

  @override
  State<FlagBuilder> createState() => _FlagBuilderState();
}

class _FlagBuilderState extends State<FlagBuilder> {
  late bool _enabled;
  StreamSubscription<FlagSnapshot>? _sub;

  @override
  void initState() {
    super.initState();
    _enabled = widget.client.isEnabled(widget.flagName,
        defaultValue: widget.defaultValue);
    _sub = widget.client.snapshotStream.listen(_onSnapshot);
  }

  @override
  void didUpdateWidget(FlagBuilder oldWidget) {
    super.didUpdateWidget(oldWidget);
    // If the client or flag name changed, re-read the current value.
    if (oldWidget.client   != widget.client ||
        oldWidget.flagName != widget.flagName) {
      _sub?.cancel();
      _enabled = widget.client.isEnabled(widget.flagName,
          defaultValue: widget.defaultValue);
      _sub = widget.client.snapshotStream.listen(_onSnapshot);
    }
  }

  void _onSnapshot(FlagSnapshot snapshot) {
    final newEnabled =
        snapshot.flags[widget.flagName] ?? widget.defaultValue;
    // Only rebuild if the value actually changed.
    if (newEnabled != _enabled) {
      setState(() => _enabled = newEnabled);
    }
  }

  @override
  void dispose() {
    _sub?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) =>
      widget.builder(context, _enabled);
}


/// A widget that rebuilds when a typed remote config value changes.
///
/// ```dart
/// ConfigBuilder<String>(
///   client:       client,
///   configKey:    'welcome_message',
///   defaultValue: 'Welcome!',
///   builder:      (context, msg) => Text(msg),
/// )
/// ```
class ConfigBuilder<T> extends StatefulWidget {
  const ConfigBuilder({
    super.key,
    required this.client,
    required this.configKey,
    required this.defaultValue,
    required this.builder,
  });

  final FeatureFlagClient client;
  final String configKey;
  final T defaultValue;
  final Widget Function(BuildContext context, T value) builder;

  @override
  State<ConfigBuilder<T>> createState() => _ConfigBuilderState<T>();
}

class _ConfigBuilderState<T> extends State<ConfigBuilder<T>> {
  late T _value;
  StreamSubscription<FlagSnapshot>? _sub;

  @override
  void initState() {
    super.initState();
    _value = widget.client.getConfig<T>(widget.configKey, widget.defaultValue);
    _sub   = widget.client.snapshotStream.listen(_onSnapshot);
  }

  @override
  void didUpdateWidget(ConfigBuilder<T> oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.client    != widget.client ||
        oldWidget.configKey != widget.configKey) {
      _sub?.cancel();
      _value = widget.client.getConfig<T>(widget.configKey, widget.defaultValue);
      _sub   = widget.client.snapshotStream.listen(_onSnapshot);
    }
  }

  void _onSnapshot(FlagSnapshot snapshot) {
    final raw      = snapshot.configs[widget.configKey];
    final newValue = raw is T ? raw : widget.defaultValue;
    if (newValue != _value) {
      setState(() => _value = newValue);
    }
  }

  @override
  void dispose() {
    _sub?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) =>
      widget.builder(context, _value);
}
