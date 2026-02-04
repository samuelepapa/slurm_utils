# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.1] - 2025-02-04

### Fixed
- Fixed issue where `request-gpu` would fail if `~/.ssh/config` did not already have a `Host snellius_gpu_node` block.
- Added automatic creation of the SSH config block with `ProxyJump` tunneling through the login node.

## [0.1.0] - 2025-02-04

### Added
- Initial release.
- `request-gpu` command line tool for requesting GPU nodes on Snellius.
- Automatic SSH config updating (HostName only).
