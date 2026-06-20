#!/usr/bin/env python3
"""
Seed the store with the example flags and configs from the problem statement.
Run from the server/ directory:
    python seed_data.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import storage
from models import FeatureFlag, TargetingConfig, RemoteConfig


def seed():
    print("🌱  Seeding feature flags and remote configs…\n")

    # ── Feature Flags ────────────────────────────────────────────────────────
    flags = [
        FeatureFlag(
            name="new_checkout_flow",
            enabled=True,
            targeting=TargetingConfig(type="beta_users"),
            description="Redesigned checkout with fewer steps",
        ),
        FeatureFlag(
            name="dark_mode_beta",
            enabled=False,
            targeting=TargetingConfig(type="everyone"),
            description="Dark theme across all screens",
        ),
        FeatureFlag(
            name="ai_recommendations",
            enabled=True,
            targeting=TargetingConfig(type="everyone"),
            description="ML-powered product recommendations",
        ),
        FeatureFlag(
            name="10pct_price_experiment",
            enabled=True,
            targeting=TargetingConfig(type="percentage", percentage=10),
            description="Show new pricing to 10 % of users",
        ),
    ]

    # ── Remote Configs ───────────────────────────────────────────────────────
    configs = [
        RemoteConfig(
            key="welcome_message",
            value="Hello, World!",
            type="string",
            description="Banner text shown on the home screen",
        ),
        RemoteConfig(
            key="max_login_attempts",
            value="5",
            type="number",
            description="Lock-out threshold before CAPTCHA",
        ),
        RemoteConfig(
            key="items_per_page",
            value="20",
            type="number",
            description="Pagination size for listing endpoints",
        ),
        RemoteConfig(
            key="maintenance_mode",
            value="false",
            type="boolean",
            description="Flip to true to show maintenance banner",
        ),
    ]

    # ── Write (skip duplicates) ───────────────────────────────────────────────
    existing_flags = {f.name for f in storage.get_all_flags()}
    existing_configs = {c.key for c in storage.get_all_configs()}

    for flag in flags:
        if flag.name in existing_flags:
            print(f"  ⚠  Flag '{flag.name}' already exists — skipped")
        else:
            storage.create_flag(flag)
            status = "ON " if flag.enabled else "OFF"
            print(f"  ✅ Flag created: [{status}] {flag.name}")

    print()

    for config in configs:
        if config.key in existing_configs:
            print(f"  ⚠  Config '{config.key}' already exists — skipped")
        else:
            storage.create_config(config)
            print(f"  ✅ Config created: {config.key} = {config.value!r}")

    print("\n✨  Seed complete!")


if __name__ == "__main__":
    seed()
