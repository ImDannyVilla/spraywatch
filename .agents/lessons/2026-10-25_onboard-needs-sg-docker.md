---
date: 2026-10-25
issue:
area: gb10
severity: important
---

# A second sandbox's onboarding fails preflight unless it runs as group docker

## What happened

`scripts/nemoclaw/onboard.sh` stopped at "[1/8] Preflight checks" with "System readiness could not confirm required capabilities: gateway.version.compatible, gateway.port.uncontested. Gateway port 8080 could not be observed completely", although the gateway was healthy and ClearFrame's sandbox was using it. `id -nG` listed `docker`, so the script's guard didn't re-exec under `sg docker`.

## Root cause

The shared gateway (`openshell-gateway`, port 8080) had been started under `sg docker`, so its primary group is `docker`. Preflight identifies the port's listener with `lsof`, which needs the caller's group to match the process's. A shell where `docker` is only a supplementary group sees the port but not its owner, so ownership is "inconclusive". It's the same symptom as ClearFrame's `nemoclaw-needs-docker-group` lesson, but the group was present this time.

## Fix

`onboard.sh` now always re-executes itself once under `sg docker` (guarded by `SPRAYWATCH_UNDER_SG=1`), whatever `id -nG` says. Check with `sg docker -c 'lsof -i :8080 -sTCP:LISTEN -P -n'`: it should name the `openshell` gateway.

## Prevention

The guard in `scripts/nemoclaw/onboard.sh`. Run any `nemoclaw onboard` on the GB10 under `sg docker -c '...'`, not only from a shell that has the group.
