# Slurm Utilities

This repository contains utility scripts for managing Slurm jobs on a remote cluster you reach over SSH.

## Installation

Install this with [uv](https://docs.astral.sh/uv/) as a tool. That is the supported way: it puts the
`request-gpu` and `slurm-resources` executables on your `PATH`, each in its own isolated environment, so
they never clash with the Python environment you happen to be working in.

Straight from GitHub, no clone needed:

```bash
uv tool install git+https://github.com/samuelepapa/slurm_utils
```

Or from a local checkout:

```bash
uv tool install .
```

If this is your first `uv tool install`, run `uv tool update-shell` once and restart your shell so that
`~/.local/bin` is on your `PATH`.

To upgrade, reinstall, or remove:

```bash
uv tool upgrade slurm-utils
uv tool install --force git+https://github.com/samuelepapa/slurm_utils
uv tool uninstall slurm-utils
```

To run a command once without installing anything:

```bash
uvx --from git+https://github.com/samuelepapa/slurm_utils request-gpu -- --gres=gpu:1
uvx --from git+https://github.com/samuelepapa/slurm_utils slurm-resources
```

`pip install .` still works if you prefer it, but then the commands live in whichever environment you
installed them into.

### Development

```bash
uv sync          # create .venv and install the package plus dev dependencies
uv run pytest    # run the test suite
```

Use `uv tool install --editable .` if you want the system-wide commands to track your local edits.

## Shell completion

Every command in this package supports the same two completion flags. Set a command up once:

```bash
request-gpu --setup-completion zsh       # or: bash
slurm-resources --setup-completion zsh
```

This writes the completion script to `~/.config/slurm_utils/completion.<command>.<shell>` and appends a
line to `~/.zshrc` (or `~/.bashrc`) that sources it. Open a new shell to start using it. Re-running the
command refreshes the script without duplicating the line in your shell config.

The scripts are generated from each command's own argument parser, so they always cover the full option
set. Options that take a hostname (`--host`, `--proxy-host`) complete from the `Host` aliases declared in
`~/.ssh/config` and any files it `Include`s; `--list-ssh-hosts` prints that same list.

## Configuration

Both commands need the hostname of a login node that can run Slurm commands. Pass it with `--host`, or
set it once so you never have to type it:

```bash
export SLURM_LOGIN_HOST=mycluster
```

The value is usually a `Host` alias from your `~/.ssh/config`, so that SSH already knows the real
hostname, username, and jump host to use.

## Scripts

### `request_gpu`

This tool automates the process of requesting a GPU node on a Slurm cluster and updating your local SSH configuration to allow direct access to the assigned node.

It performs the following steps:
1. Submits an interactive-like job (sleeping) to the Slurm queue.
2. Waits for the job to start and retrieves the assigned node name.
3. Updates your `~/.ssh/config` file with a local SSH alias for the assigned compute node, reusing the
   username that SSH already resolves for the login host.
4. Tracks active requests locally so multiple allocations receive distinct SSH aliases.

#### Usage

After installation, you can use the command `request-gpu` directly:

```bash
request-gpu [ssh-options] -- [sbatch-options]
```

#### Options

- `--user`: Username on the cluster. If omitted, it is taken from the `User` that SSH resolves for `--host`, which is your local username when the SSH config does not set one.
- `--host`: Login node hostname used to run `sbatch` and `squeue`. Defaults to the `SLURM_LOGIN_HOST` environment variable, and is required when that variable is not set.
- `--ssh-name`: Local SSH config alias to create or update. If omitted, the tool uses `slurm_gpu_node`, then `slurm_gpu_node_2`, and so on for multiple active requests.
- `--proxy-host`: Host to use as `ProxyJump` in new SSH config entries. If omitted, this defaults to `--host`.
- `--identity-file`: SSH private key to write as `IdentityFile` in the generated SSH config entry. When omitted, matching identity settings are copied from the proxy host entry when available.
- `--email`: Email address to notify when the Slurm job starts running. This adds Slurm's `--mail-user` and `--mail-type=BEGIN` options.
- `--setup-completion`: Install `bash` or `zsh` completion and exit.
- `--list-ssh-hosts`: Print the `Host` aliases found in the local SSH config and exit.

All Slurm options must be passed after `--`. The tool does not add a default partition, time limit, GPU count, or GRES request. It only appends `--wrap='sleep infinity'` to keep the allocation alive.

#### Example

Request two GPUs for 2 hours on the `gpu` partition:

```bash
request-gpu -- --partition=gpu --time=02:00:00 --gres=gpu:2 -n 1 --cpus-per-task=8
```

Request a GPU and receive an email when the job starts running:

```bash
request-gpu --email you@example.com -- --partition=gpu --gres=gpu:1
```

Use a custom SSH alias and tunnel proxy host:

```bash
request-gpu --ssh-name my_gpu_node --proxy-host cluster-tunnel -- --partition=gpu --time=02:00:00 --gres=gpu:1
```

Use a custom SSH identity file:

```bash
request-gpu --ssh-name mycluster_2_gpus --host mycluster --proxy-host mycluster --identity-file ~/.ssh/id_rsa_cluster -- --gres=gpu:2
```

After the script completes, you can SSH directly to the node:

```bash
ssh slurm_gpu_node
```

For the custom alias example:

```bash
ssh my_gpu_node
```

### `slurm-resources`

This tool connects to a login node, reads the cluster's node inventory with `scontrol show nodes`, and
opens an interactive browser showing how many GPUs, CPUs, and how much RAM are free versus allocated.

Nodes with identical hardware (GPU model and count, CPU count, memory, partitions) are grouped together,
with GPU groups listed first. Nodes that cannot accept work (`DOWN`, `DRAIN`, `MAINT`, ...) are excluded
from the free totals and shown with the reason they are out.

#### Usage

```bash
slurm-resources [--host LOGIN_HOST] [--partition PARTITION] [--plain]
```

You start on the overview, one row per resource type, and drill into a group to see its nodes. On large
clusters the node list is sorted with the emptiest nodes first, so the capacity you can actually use is
always at the top.

| Key | Action |
| --- | --- |
| `↑` `↓` `PgUp` `PgDn` `Home` `End` | Move |
| `→` or `Enter` | Open the selected group, or show node details |
| `←` or `Backspace` | Go back |
| `a` `f` `p` `u` `d` | Show all / free / partial / fully used / down nodes |
| `/` | Search by node name |
| `r` | Re-read the cluster |
| `q` | Quit |

#### Options

- `--host`: Login node hostname used to run `scontrol`. Defaults to the `SLURM_LOGIN_HOST` environment variable, and is required when that variable is not set.
- `--partition`: Only report nodes belonging to this partition.
- `--plain`: Print a plain text report instead of opening the browser. This also happens automatically
  when the output is piped or redirected, so `slurm-resources > report.txt` works as expected.
- `--setup-completion`: Install `bash` or `zsh` completion and exit.
- `--list-ssh-hosts`: Print the `Host` aliases found in the local SSH config and exit.

#### Example

```
 Slurm resources on login01
 GPUs 142/4344   CPUs 2356/71040   RAM 21.4T/1029.1T   nodes 551/557 usable
 2 resource groups

› 8x h200      GPU  142/4344 ░░░░░░░░░░   3%  CPU  2272/69504   3%  RAM 20.2T/1018.1T  2%   549 nodes  1 free  34 partial  508 full  6 down
    128 CPU, 1.9T RAM per node  ·  partitions: h200
  CPU only                                        CPU    84/1536   5%  RAM   1.1T/11.0T  10%     8 nodes  2 partial  6 full
    192 CPU, 1.4T RAM per node  ·  partitions: cpu
```

Pressing `→` on the `8x h200` row and then `p` narrows it to the partially used nodes:

```
 8x h200  ·  filter: partial  ·  showing 34 of 549 nodes

› h200-bar-196-013   partial   6/8 GPU  ██████░░   96/128 CPU  ██████░░   296G/1.9T RAM  █░░░░░░░
  h200-bar-197-217   partial   6/8 GPU  ██████░░   96/128 CPU  ██████░░   634G/1.9T RAM  ███░░░░░
```
