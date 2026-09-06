# Slurm Utilities

This repository contains utility scripts for managing Slurm jobs, specifically tailored for the Snellius cluster.

## Scripts

### `request_gpu`

This tool automates the process of requesting a GPU node on Snellius and updating your local SSH configuration to allow direct access to the assigned node.

It performs the following steps:
1. Submits an interactive-like job (sleeping) to the Slurm queue.
2. Waits for the job to start and retrieves the assigned node name.
3. Updates your `~/.ssh/config` file with a local SSH alias for the assigned compute node.
4. Tracks active requests locally so multiple allocations receive distinct SSH aliases.

#### Installation

To install the package, run the following command in the repository root:

```bash
pip install .
```

To install in editable mode (for development):

```bash
pip install -e .
```

#### Usage

After installation, you can use the command `request-gpu` directly:

```bash
request-gpu [ssh-options] -- [sbatch-options]
```

#### Options

- `--user`: Username on the cluster (default: "spapa01").
- `--host`: Login node hostname used to run `sbatch` and `squeue` (default: "snellius01").
- `--ssh-name`: Local SSH config alias to create or update. If omitted, the tool uses `snellius_gpu_node`, then `snellius_gpu_node_2`, and so on for multiple active requests.
- `--proxy-host`: Host to use as `ProxyJump` in new SSH config entries. If omitted, this defaults to `--host`.
- `--identity-file`: SSH private key to write as `IdentityFile` in the generated SSH config entry. When omitted, matching identity settings are copied from the proxy host entry when available.
- `--email`: Email address to notify when the Slurm job starts running. This adds Slurm's `--mail-user` and `--mail-type=BEGIN` options.

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
request-gpu --ssh-name my_gpu_node --proxy-host snellius-tunnel -- --partition=gpu --time=02:00:00 --gres=gpu:1
```

Use a custom SSH identity file:

```bash
request-gpu --ssh-name hipster_2_gpus --host hipster --proxy-host hipster --identity-file ~/.ssh/id_rsa_cuteandcuter -- --gres=gpu:2
```

After the script completes, you can SSH directly to the node:

```bash
ssh snellius_gpu_node
```

For the custom alias example:

```bash
ssh my_gpu_node
```
