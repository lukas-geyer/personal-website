---
version: 0.1 (Phase 1)
title: Shared Rust Core & FSRS-7 Scheduler
date: 2026-11-21
platform: Rust Core · iOS & macOS (planned)
highlights: Foundational muninn-core Rust workspace, collection data model, and FSRS-7 spaced-repetition scheduler
---

**Phase 1: Core** laid a fast, portable foundation before the native apps. It was finished on 24 November 2026.

### What's Built

- **Shared Rust Workspace (`muninn-core`):** Houses the collection data model, review log, file format, and scheduling logic once so every platform behaves identically.
- **FSRS-7 Scheduler:** Modern spaced-repetition scheduling tuned for long-term retention without manual ease-factor babysitting.
- **Lossless Anki Architecture:** Designed to convert imported `.apkg` decks into clean native card types while retaining original templates for lossless round-trip export.

### Up Next

The first native app for iPhone (see version 0.2), then macOS, followed by cross-device sync and native Android, Windows, and Linux apps.
