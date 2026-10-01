"""Plumbing shared by the slurm_utils command line tools."""

import glob
import os

from slurm_utils.completion import SHELLS, install_completion

CONFIG_DIR_NAME = "slurm_utils"
DEFAULT_SSH_CONFIG_PATH = "~/.ssh/config"
HOST_PATTERN_CHARS = set("*?!")


def get_config_dir():
    config_home = os.environ.get("XDG_CONFIG_HOME")
    if not config_home:
        config_home = os.path.expanduser("~/.config")
    return os.path.join(config_home, CONFIG_DIR_NAME)


def list_ssh_config_hosts(path=None, base_dir=None, visited=None):
    """Collect the concrete Host aliases declared in an SSH config and its includes."""
    path = os.path.expanduser(path or DEFAULT_SSH_CONFIG_PATH)
    base_dir = base_dir if base_dir is not None else os.path.dirname(path)
    visited = visited if visited is not None else set()

    real_path = os.path.realpath(path)
    if real_path in visited:
        return []
    visited.add(real_path)

    try:
        with open(path, "r") as f:
            lines = f.readlines()
    except OSError:
        return []

    hosts = []
    for line in lines:
        parts = line.strip().split()
        if not parts or parts[0].startswith("#"):
            continue

        keyword = parts[0].lower()
        if keyword == "host":
            hosts.extend(name for name in parts[1:] if not HOST_PATTERN_CHARS & set(name))
        elif keyword == "include":
            for pattern in parts[1:]:
                pattern = os.path.expanduser(pattern)
                if not os.path.isabs(pattern):
                    pattern = os.path.join(base_dir, pattern)
                for included in sorted(glob.glob(pattern)):
                    hosts.extend(list_ssh_config_hosts(included, base_dir, visited))

    return list(dict.fromkeys(hosts))


def add_completion_arguments(parser):
    """Add the flags every command exposes for shell completion."""
    parser.add_argument(
        "--setup-completion",
        choices=SHELLS,
        default=None,
        metavar="shell",
        help="Install shell completion for the given shell and exit",
    )
    parser.add_argument(
        "--list-ssh-hosts",
        action="store_true",
        help="List Host aliases found in the local SSH config and exit",
    )
    return parser


def handle_completion_arguments(args, prog, parser, completers=None):
    """Run the completion helper flags. Returns True when the command should stop."""
    if args.setup_completion:
        script_path, rc_path, already_sourced = install_completion(
            args.setup_completion, prog, parser, get_config_dir(), completers
        )
        print(f"Wrote {args.setup_completion} completion to {script_path}")
        if already_sourced:
            print(f"{rc_path} already sources it")
        else:
            print(f"Added a source line to {rc_path}")
        print(f"Run 'source {script_path}' or restart your shell to start using it")
        return True

    if args.list_ssh_hosts:
        for host in list_ssh_config_hosts():
            print(host)
        return True

    return False
