# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed
- Switched the build backend to `uv_build` so the package can be installed system-wide with `uv tool install`.
- Raised the minimum Python version to 3.9.
- `--user` is now optional: the cluster username is read from the SSH config entry of `--host` instead of defaulting to a hardcoded account.
- Shell completion scripts are now generated from each command's argument parser instead of being hardcoded for `request-gpu`, so every command gets `--setup-completion` and `--list-ssh-hosts` and can never drift from its own options.
- Completion scripts are now written to `~/.config/slurm_utils/completion.<command>.<shell>` so commands do not overwrite each other. If you installed completion before this change, remove the line sourcing the old `completion.<shell>` file from your shell rc.
- Documented `uv tool install` as the supported way to install this package, in a top-level README section covering every command instead of only `request-gpu`.

### Added
- Added the `slurm-resources` command, which reports free and allocated GPUs, CPUs, and RAM grouped by resource type with GPU groups first.
- `slurm-resources` opens an interactive browser (arrow keys to move, `→`/`←` to drill into a group or node, `a`/`f`/`p`/`u`/`d` to filter, `/` to search, `r` to refresh) so that large clusters stay readable. It falls back to the plain text report with `--plain` or whenever the output is not a terminal.
- Added a `uv.lock` lockfile and a `dev` dependency group for running the test suite with `uv run pytest`.
- Added `--email` to `request-gpu` for notifications when the job starts running.
- Added `request-gpu --setup-completion bash|zsh`, which installs a completion script that completes `--host` and `--proxy-host` from the SSH config Host aliases.
- Added `request-gpu --list-ssh-hosts`, which lists the Host aliases declared in `~/.ssh/config` and the files it includes.

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
