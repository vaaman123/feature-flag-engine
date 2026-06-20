/// Data models for the Feature Flag Flutter SDK.
library;

// ── Targeting Config ────────────────────────────────────────────────────────

enum TargetingType { everyone, betaUsers, percentage, userIds, unknown }

class TargetingConfig {
  final TargetingType type;
  final double? percentage;
  final List<String> userIds;

  const TargetingConfig({
    this.type = TargetingType.everyone,
    this.percentage,
    this.userIds = const [],
  });

  factory TargetingConfig.fromJson(Map<String, dynamic> json) {
    final typeStr = json['type'] as String? ?? 'everyone';
    final type = switch (typeStr) {
      'everyone'   => TargetingType.everyone,
      'beta_users' => TargetingType.betaUsers,
      'percentage' => TargetingType.percentage,
      'user_ids'   => TargetingType.userIds,
      _            => TargetingType.unknown,
    };
    return TargetingConfig(
      type: type,
      percentage: (json['percentage'] as num?)?.toDouble(),
      userIds: (json['user_ids'] as List<dynamic>?)
              ?.map((e) => e.toString())
              .toList() ??
          [],
    );
  }

  String get displayName => switch (type) {
    TargetingType.everyone   => 'Everyone',
    TargetingType.betaUsers  => 'Beta Users',
    TargetingType.percentage => '${percentage?.toStringAsFixed(0) ?? 0}% Rollout',
    TargetingType.userIds    => '${userIds.length} User(s)',
    TargetingType.unknown    => 'Unknown',
  };
}

// ── Feature Flag ────────────────────────────────────────────────────────────

class FeatureFlag {
  final String id;
  final String name;
  final bool enabled;
  final TargetingConfig targeting;
  final String description;
  final String updatedAt;

  const FeatureFlag({
    required this.id,
    required this.name,
    required this.enabled,
    required this.targeting,
    this.description = '',
    this.updatedAt = '',
  });

  factory FeatureFlag.fromJson(Map<String, dynamic> json) => FeatureFlag(
        id: json['id'] as String,
        name: json['name'] as String,
        enabled: json['enabled'] as bool? ?? false,
        targeting: TargetingConfig.fromJson(
            json['targeting'] as Map<String, dynamic>? ?? {}),
        description: json['description'] as String? ?? '',
        updatedAt: json['updated_at'] as String? ?? '',
      );
}

// ── Remote Config ───────────────────────────────────────────────────────────

enum ConfigType { string, number, boolean }

class RemoteConfig {
  final String id;
  final String key;
  final String rawValue;
  final ConfigType type;
  final String description;
  final String updatedAt;

  const RemoteConfig({
    required this.id,
    required this.key,
    required this.rawValue,
    this.type = ConfigType.string,
    this.description = '',
    this.updatedAt = '',
  });

  factory RemoteConfig.fromJson(Map<String, dynamic> json) {
    final typeStr = json['type'] as String? ?? 'string';
    final type = switch (typeStr) {
      'number'  => ConfigType.number,
      'boolean' => ConfigType.boolean,
      _         => ConfigType.string,
    };
    return RemoteConfig(
      id: json['id'] as String,
      key: json['key'] as String,
      rawValue: json['value'] as String? ?? '',
      type: type,
      description: json['description'] as String? ?? '',
      updatedAt: json['updated_at'] as String? ?? '',
    );
  }

  /// Returns the value cast to its declared type.
  dynamic get parsedValue => switch (type) {
    ConfigType.number  => num.tryParse(rawValue) ?? rawValue,
    ConfigType.boolean =>
      rawValue.trim().toLowerCase() == 'true' ||
      rawValue.trim() == '1' ||
      rawValue.trim().toLowerCase() == 'yes',
    ConfigType.string  => rawValue,
  };
}

// ── WebSocket Events ────────────────────────────────────────────────────────

enum FlagEvent {
  initialState,
  flagCreated,
  flagUpdated,
  flagDeleted,
  configCreated,
  configUpdated,
  configDeleted,
  unknown,
}

extension FlagEventParsing on String {
  FlagEvent toFlagEvent() => switch (this) {
    'initial_state'    => FlagEvent.initialState,
    'flag_created'     => FlagEvent.flagCreated,
    'flag_updated'     => FlagEvent.flagUpdated,
    'flag_deleted'     => FlagEvent.flagDeleted,
    'config_created'   => FlagEvent.configCreated,
    'config_updated'   => FlagEvent.configUpdated,
    'config_deleted'   => FlagEvent.configDeleted,
    _                  => FlagEvent.unknown,
  };
}

// ── State Snapshot ──────────────────────────────────────────────────────────

class FlagSnapshot {
  final Map<String, bool> flags;
  final Map<String, dynamic> configs;

  const FlagSnapshot({
    this.flags = const {},
    this.configs = const {},
  });

  FlagSnapshot copyWith({
    Map<String, bool>? flags,
    Map<String, dynamic>? configs,
  }) =>
      FlagSnapshot(
        flags: flags ?? this.flags,
        configs: configs ?? this.configs,
      );
}
