# serverless-builder Agent Instructions

## Platform Rules Bridge

Follow the Lara Health platform workspace rules from the workspace-level `AGENTS.md`. This repository has no repo-specific override file at this time.

## Command Source of Truth

Use `.lara/repo-manifest.yml` as the command source of truth for setup, validation, and build commands. Do not invent missing commands; if a command is unavailable in the manifest, report it as unavailable with the manifest evidence instead of guessing.
