/// Feature Flag Engine — Flutter Example App
///
/// Demonstrates:
///   • Initialising FeatureFlagClient and injecting it with InheritedWidget
///   • StreamBuilder for reactive UI updates on every flag/config change
///   • isEnabled() for conditional feature rendering
///   • getConfig<T>() for typed remote config values
///   • Pull-to-refresh to force a re-evaluate
///   • A debug panel listing every known flag and config

import 'package:flutter/material.dart';
import 'package:feature_flag_flutter/feature_flag_flutter.dart';

// ─── Configuration ───────────────────────────────────────────────────────────

/// Change this to match your server address.
/// On Android emulator use http://10.0.2.2:8000
/// On iOS simulator / desktop use http://localhost:8000
const String kServerUrl = 'http://localhost:8000';
const String kUserId    = 'demo_user_001';
const bool   kIsBeta    = true;   // flip to false to test non-beta targeting

// ─── main ────────────────────────────────────────────────────────────────────

void main() async {
  WidgetsFlutterBinding.ensureInitialized();

  final client = FeatureFlagClient(
    serverUrl: kServerUrl,
    userId: kUserId,
    isBetaUser: kIsBeta,
  );

  // Initialize (fetches state + opens WebSocket)
  await client.initialize();

  runApp(FlagClientProvider(client: client, child: const MyApp()));
}

// ─── InheritedWidget: makes the client available anywhere in the tree ────────

class FlagClientProvider extends InheritedWidget {
  const FlagClientProvider({
    super.key,
    required this.client,
    required super.child,
  });

  final FeatureFlagClient client;

  static FeatureFlagClient of(BuildContext context) {
    final provider =
        context.dependOnInheritedWidgetOfExactType<FlagClientProvider>();
    assert(provider != null, 'No FlagClientProvider found in context');
    return provider!.client;
  }

  @override
  bool updateShouldNotify(FlagClientProvider oldWidget) =>
      client != oldWidget.client;
}

// ─── App ─────────────────────────────────────────────────────────────────────

class MyApp extends StatelessWidget {
  const MyApp({super.key});

  @override
  Widget build(BuildContext context) {
    final client = FlagClientProvider.of(context);

    // Wrap the whole app in a StreamBuilder so theme can react to flags
    return StreamBuilder<FlagSnapshot>(
      stream: client.snapshotStream,
      initialData: client.snapshot,
      builder: (context, snapshot) {
        final darkMode = client.isEnabled('dark_mode_beta');
        return MaterialApp(
          title: 'Flag Engine Demo',
          debugShowCheckedModeBanner: false,
          themeMode: darkMode ? ThemeMode.dark : ThemeMode.light,
          theme: ThemeData(
            colorScheme: ColorScheme.fromSeed(
              seedColor: Colors.indigo,
              brightness: Brightness.light,
            ),
            useMaterial3: true,
          ),
          darkTheme: ThemeData(
            colorScheme: ColorScheme.fromSeed(
              seedColor: Colors.indigo,
              brightness: Brightness.dark,
            ),
            useMaterial3: true,
          ),
          home: const HomePage(),
        );
      },
    );
  }
}

// ─── Home Page ───────────────────────────────────────────────────────────────

class HomePage extends StatelessWidget {
  const HomePage({super.key});

  @override
  Widget build(BuildContext context) {
    final client = FlagClientProvider.of(context);

    return StreamBuilder<FlagSnapshot>(
      stream: client.snapshotStream,
      initialData: client.snapshot,
      builder: (context, snapshot) {
        final darkMode = client.isEnabled('dark_mode_beta');

        return Scaffold(
          appBar: AppBar(
            title: const Text('🚀 Flag Engine Demo'),
            actions: [
              // Live connection indicator
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 16),
                child: Icon(
                  Icons.circle,
                  size: 12,
                  color: client.isConnected ? Colors.greenAccent : Colors.red,
                ),
              ),
            ],
          ),
          body: RefreshIndicator(
            onRefresh: client.refresh,
            child: ListView(
              padding: const EdgeInsets.all(16),
              children: [
                // ── Welcome Banner — ConfigBuilder rebuilds only when this config changes
                ConfigBuilder<String>(
                  client:       client,
                  configKey:    'welcome_message',
                  defaultValue: 'Welcome!',
                  builder:      (_, msg) => _BannerCard(message: msg),
                ),
                const SizedBox(height: 16),

                // ── User context chip row ──────────────────────────────────
                Wrap(
                  spacing: 8,
                  children: [
                    _InfoChip(label: 'User',     value: kUserId),
                    _InfoChip(label: 'Beta',     value: kIsBeta.toString()),
                    _InfoChip(
                      label: 'Dark Mode',
                      value: darkMode ? 'ON' : 'OFF',
                      color: darkMode ? Colors.deepPurple : null,
                    ),
                  ],
                ),
                const SizedBox(height: 24),

                // ── Feature: AI Recommendations — FlagBuilder is O(1) rebuild
                FlagBuilder(
                  client:   client,
                  flagName: 'ai_recommendations',
                  builder:  (_, enabled) => enabled
                      ? Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                          const _SectionHeader('✨ AI Recommendations'),
                          const _AiRecommendationsWidget(),
                          const SizedBox(height: 24),
                        ])
                      : const SizedBox.shrink(),
                ),

                // ── Feature: New Checkout Flow — FlagBuilder
                const _SectionHeader('🛒 Checkout'),
                FlagBuilder(
                  client:   client,
                  flagName: 'new_checkout_flow',
                  builder:  (_, enabled) => enabled
                      ? const _NewCheckoutWidget()
                      : const _LegacyCheckoutWidget(),
                ),
                const SizedBox(height: 24),

                // ── Debug Panel ───────────────────────────────────────────
                _DebugPanel(client: client),
              ],
            ),
          ),
        );
      },
    );
  }
}

// ─── Banner Card ─────────────────────────────────────────────────────────────

class _BannerCard extends StatelessWidget {
  const _BannerCard({required this.message});
  final String message;

  @override
  Widget build(BuildContext context) {
    return Card(
      color: Theme.of(context).colorScheme.primaryContainer,
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Row(
          children: [
            const Icon(Icons.campaign_outlined, size: 28),
            const SizedBox(width: 12),
            Expanded(
              child: Text(
                message,
                style: Theme.of(context).textTheme.titleMedium?.copyWith(
                      fontWeight: FontWeight.w600,
                    ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

// ─── Info Chip ───────────────────────────────────────────────────────────────

class _InfoChip extends StatelessWidget {
  const _InfoChip({required this.label, required this.value, this.color});
  final String label;
  final String value;
  final Color? color;

  @override
  Widget build(BuildContext context) {
    return Chip(
      avatar: Icon(Icons.label_outline, size: 16, color: color),
      label: Text('$label: $value',
          style: TextStyle(color: color, fontSize: 12)),
    );
  }
}

// ─── Section Header ──────────────────────────────────────────────────────────

class _SectionHeader extends StatelessWidget {
  const _SectionHeader(this.title);
  final String title;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(bottom: 8),
        child: Text(title, style: Theme.of(context).textTheme.titleMedium),
      );
}

// ─── AI Recommendations Widget ───────────────────────────────────────────────

class _AiRecommendationsWidget extends StatelessWidget {
  const _AiRecommendationsWidget();

  static const _items = [
    ('⌚ Smart Watch Pro', 'Based on your browsing'),
    ('🎧 Wireless Earbuds', 'Frequently bought together'),
    ('📱 Phone Stand',     'Trending in Electronics'),
  ];

  @override
  Widget build(BuildContext context) {
    return Column(
      children: _items
          .map((item) => Card(
                margin: const EdgeInsets.only(bottom: 8),
                child: ListTile(
                  leading: Text(item.$1.substring(0, 2),
                      style: const TextStyle(fontSize: 24)),
                  title: Text(item.$1.substring(3)),
                  subtitle: Text(item.$2),
                  trailing: FilledButton.tonal(
                    onPressed: () {},
                    child: const Text('Add'),
                  ),
                ),
              ))
          .toList(),
    );
  }
}

// ─── New Checkout Widget ─────────────────────────────────────────────────────

class _NewCheckoutWidget extends StatelessWidget {
  const _NewCheckoutWidget();

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Container(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                  decoration: BoxDecoration(
                    color: Colors.green.shade100,
                    borderRadius: BorderRadius.circular(4),
                  ),
                  child: Text('NEW',
                      style: TextStyle(
                          color: Colors.green.shade800,
                          fontSize: 10,
                          fontWeight: FontWeight.bold)),
                ),
                const SizedBox(width: 8),
                const Text('Express Checkout',
                    style: TextStyle(fontWeight: FontWeight.w600)),
              ],
            ),
            const SizedBox(height: 12),
            const Text('1 tap • Saved address • Apple/Google Pay',
                style: TextStyle(color: Colors.grey)),
            const SizedBox(height: 16),
            SizedBox(
              width: double.infinity,
              child: FilledButton.icon(
                onPressed: () {},
                icon: const Icon(Icons.bolt),
                label: const Text('Express Checkout'),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

// ─── Legacy Checkout Widget ──────────────────────────────────────────────────

class _LegacyCheckoutWidget extends StatelessWidget {
  const _LegacyCheckoutWidget();

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('Standard Checkout',
                style: TextStyle(fontWeight: FontWeight.w600)),
            const SizedBox(height: 12),
            const Text('Step 1: Shipping → Step 2: Payment → Step 3: Review',
                style: TextStyle(color: Colors.grey, fontSize: 12)),
            const SizedBox(height: 16),
            SizedBox(
              width: double.infinity,
              child: OutlinedButton.icon(
                onPressed: () {},
                icon: const Icon(Icons.shopping_cart_checkout),
                label: const Text('Proceed to Checkout'),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

// ─── Debug Panel ─────────────────────────────────────────────────────────────

class _DebugPanel extends StatefulWidget {
  const _DebugPanel({required this.client});
  final FeatureFlagClient client;

  @override
  State<_DebugPanel> createState() => _DebugPanelState();
}

class _DebugPanelState extends State<_DebugPanel> {
  bool _expanded = false;

  @override
  Widget build(BuildContext context) {
    final snapshot = widget.client.snapshot;

    return Card(
      color: Theme.of(context).colorScheme.surfaceContainerHighest,
      child: ExpansionTile(
        initiallyExpanded: _expanded,
        onExpansionChanged: (v) => setState(() => _expanded = v),
        leading: const Icon(Icons.bug_report_outlined),
        title: Text('Debug Panel  '
            '(${snapshot.flags.length} flags · '
            '${snapshot.configs.length} configs)'),
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _debugLabel(context, '── Feature Flags ──'),
                ...snapshot.flags.entries.map((e) => _FlagRow(
                      name: e.key,
                      value: e.value,
                    )),
                const SizedBox(height: 8),
                _debugLabel(context, '── Remote Configs ──'),
                ...snapshot.configs.entries.map((e) => _ConfigRow(
                      key_: e.key,
                      value: e.value,
                    )),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _debugLabel(BuildContext context, String text) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 6),
        child: Text(text,
            style: Theme.of(context)
                .textTheme
                .labelSmall
                ?.copyWith(color: Colors.grey)),
      );
}

class _FlagRow extends StatelessWidget {
  const _FlagRow({required this.name, required this.value});
  final String name;
  final bool value;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 2),
      child: Row(
        children: [
          Icon(
            value ? Icons.toggle_on : Icons.toggle_off,
            color: value ? Colors.green : Colors.red,
            size: 20,
          ),
          const SizedBox(width: 8),
          Text(name, style: const TextStyle(fontFamily: 'monospace')),
          const Spacer(),
          Text(
            value ? 'ON' : 'OFF',
            style: TextStyle(
              color: value ? Colors.green : Colors.red,
              fontWeight: FontWeight.bold,
              fontSize: 11,
            ),
          ),
        ],
      ),
    );
  }
}

class _ConfigRow extends StatelessWidget {
  const _ConfigRow({required this.key_, required this.value});
  final String key_;
  final dynamic value;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 2),
      child: Row(
        children: [
          const Icon(Icons.data_object, size: 18, color: Colors.blueGrey),
          const SizedBox(width: 8),
          Text(key_, style: const TextStyle(fontFamily: 'monospace')),
          const Spacer(),
          Text(
            value.toString(),
            style: const TextStyle(
              fontFamily: 'monospace',
              fontSize: 12,
              color: Colors.blueGrey,
            ),
          ),
        ],
      ),
    );
  }
}
