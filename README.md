# Slurm Utilities

This repository contains utility scripts for managing Slurm jobs, specifically tailored for the Snellius cluster.

## Scripts

### `request_gpu.py`

This script automates the process of requesting a GPU node on Snellius and updating your local SSH configuration to allow direct access to the assigned node.

It performs the following steps:
1. Submits an interactive-like job (sleeping) to the Slurm queue.
2. Waits for the job to start and retrieves the assigned node name.
3. Updates your `~/.ssh/config` file to map `Host snellius_gpu_node` to the assigned compute node.

#### Usage

```bash
python request_gpu.py [options]
```

#### Options

- `--time`: Job duration in HH:MM:SS format (default: "01:00:00").
- `--partition`: Slurm partition to use (default: "gpu").
- `--gpus`: Number of GPUs to request (default: "1").
- `--user`: Username on the cluster (default: "spapa01").
- `--host`: Login node hostname (default: "snellius01").

#### Example

Request a GPU for 2 hours on the 'gpu' partition:

```bash
python request_gpu.py --time 02:00:00 --partition gpu
```

After the script completes, you can SSH directly to the node:

```bash
ssh snellius_gpu_node
```
