---
version: 2.4
title: Adaptive Exam Recalculation & Live Activities
date: 2026-11-02
platform: iOS 18 · iPadOS · macOS
highlights: Dynamic schedule rebalancing, Lock Screen Live Activities, faster .ics calendar parsing
---

Semestra 2.4 focuses on what happens when a semester refuses to stay still. Lectures get moved, extra tutorials appear mid-week, and personal plans collide with revision blocks.

### What's New

- **Automatic Plan Recalculation:** When a subscribed university `.ics` feed shifts a class or exam date, Semestra quietly rebalances upcoming study blocks across your remaining free windows—preserving rest days where possible.
- **Lock Screen & Dynamic Island Live Activities:** Active focus timers and next-session countdowns now stay glanceable without unlocking your iPhone.
- **Dedicated Calendar Sync:** Sync study blocks into a dedicated iOS calendar while respecting personal events as busy time.

### Under the Hood

Calendar diffing is now processed incrementally on-device, cutting refresh times on large university feeds by over half and improving iCloud sync reliability between iPhone, iPad, and Mac.
