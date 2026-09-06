# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Added `--email` to `request-gpu` for notifications when the job starts running.

## [0.2.1] - 2026-07-07

### Fixed
- Fixed stale `request-gpu` request tracking when Slurm reports `Invalid job id specified` for an old job id.

## [0.2.0] - 2026-06-27

### Changed
- Split `request-gpu` options so SSH/local settings are passed before `--` and all Slurm `sbatch` options are forwarded after `--`.
- Removed default Slurm GPU, partition, and time arguments.

### Added
- Added configurable SSH aliases with `--ssh-name` and configurable tunnel hosts with `--proxy-host`.
- Added `--identity-file` for writing a custom SSH key into generated compute-node SSH config entries.
- Added local request tracking so multiple active GPU allocations get distinct SSH config entries.

## [0.1.1] - 2025-02-04

### Fixed
- Fixed issue where `request-gpu` would fail if `~/.ssh/config` did not already have a `Host snellius_gpu_node` block.
- Added automatic creation of the SSH config block with `ProxyJump` tunneling through the login node.

## [0.1.0] - 2025-02-04

### Added
- Initial release.
- `request-gpu` command line tool for requesting GPU nodes on Snellius.
- Automatic SSH config updating (HostName only).
