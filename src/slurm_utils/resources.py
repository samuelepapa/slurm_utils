"""Report available and allocated GPU, CPU, and memory resources on a Slurm cluster."""

import argparse
import os
import re
import subprocess
import sys
from collections import Counter, OrderedDict

from slurm_utils.cli import add_completion_arguments, handle_completion_arguments
from slurm_utils.completion import SSH_HOST

COMMAND_NAME = "slurm-resources"
LOGIN_HOST_ENV_VAR = "SLURM_LOGIN_HOST"
COMPLETERS = {"--host": SSH_HOST}

# States in which a node cannot accept new work, so its idle resources are not really free.
UNAVAILABLE_STATES = {
    "DOWN",
    "DRAIN",
    "DRAINED",
    "DRAINING",
    "FAIL",
    "FAILING",
    "FUTURE",
    "INVAL",
    "MAINT",
    "NO_RESPOND",
    "NOT_RESPONDING",
    "POWER_DOWN",
    "POWERED_DOWN",
    "POWERING_DOWN",
    "UNKNOWN",
}

KEY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*=")
TRAILING_NUMBER_RE = re.compile(r"^(.*?)(\d+)$")
MEMORY_RE = re.compile(r"^([0-9.]+)\s*([KMGTP])?", re.IGNORECASE)
MEMORY_UNITS = {"K": 1.0 / 1024, "M": 1.0, "G": 1024.0, "T": 1024.0 ** 2, "P": 1024.0 ** 3}


def build_parser():
    parser = argparse.ArgumentParser(
        prog=COMMAND_NAME,
        description="Show free and allocated GPUs, CPUs, and memory on a Slurm cluster, grouped by resource type.",
    )
    parser.add_argument(
        "--host",
        type=str,
        default=os.environ.get(LOGIN_HOST_ENV_VAR),
        help=f"Login node hostname used to run scontrol, default reads ${LOGIN_HOST_ENV_VAR}",
    )
    parser.add_argument(
        "--partition",
        type=str,
        default=None,
        help="Only report nodes belonging to this partition",
    )
    parser.add_argument(
        "--plain",
        action="store_true",
        help="Print a plain text report instead of opening the interactive browser",
    )
    return add_completion_arguments(parser)


def parse_node_record(line):
    """Turn one `scontrol show nodes --oneliner` line into a key to value mapping."""
    record = {}
    key = None
    for token in line.split():
        if KEY_RE.match(token):
            key, _, value = token.partition("=")
            record[key] = value
        elif key is not None:
            # Values such as OS= or Reason= contain spaces.
            record[key] = f"{record[key]} {token}".strip()
    return record


def parse_memory_mb(value):
    match = MEMORY_RE.match(value.strip())
    if not match:
        return 0.0
    amount = float(match.group(1))
    unit = (match.group(2) or "M").upper()
    return amount * MEMORY_UNITS[unit]


def parse_tres(value):
    """Parse a TRES string such as 'cpu=72,mem=480G,gres/gpu=4'."""
    tres = {}
    for item in value.split(","):
        name, _, amount = item.partition("=")
        name = name.strip()
        if not name or not amount:
            continue
        if name == "mem":
            tres[name] = parse_memory_mb(amount)
        else:
            try:
                tres[name] = float(amount)
            except ValueError:
                continue
    return tres


def parse_gres(value):
    """Parse a GRES string such as 'gpu:a100:4(S:0-1)' into (gpu_type, count)."""
    gpu_type = None
    count = 0
    for item in value.split(","):
        item = re.sub(r"\(.*?\)", "", item).strip()
        parts = item.split(":")
        if len(parts) < 2 or parts[0] != "gpu":
            continue
        try:
            count += int(parts[-1])
        except ValueError:
            continue
        if len(parts) >= 3:
            gpu_type = parts[1]
    return gpu_type, count


def build_node(record):
    cfg_tres = parse_tres(record.get("CfgTRES", ""))
    alloc_tres = parse_tres(record.get("AllocTRES", ""))
    gpu_type, gres_total = parse_gres(record.get("Gres", ""))
    _, gres_used = parse_gres(record.get("GresUsed", ""))

    states = [state for state in record.get("State", "").split("+") if state]
    partitions = tuple(p for p in record.get("Partitions", "").split(",") if p)

    return {
        "name": record.get("NodeName", ""),
        "states": states,
        "partitions": partitions,
        "reason": record.get("Reason", ""),
        "available": not any(state in UNAVAILABLE_STATES for state in states),
        "gpu_type": gpu_type,
        "gpu_total": int(cfg_tres.get("gres/gpu", gres_total)),
        "gpu_alloc": int(alloc_tres.get("gres/gpu", gres_used)),
        "cpu_total": int(float(record.get("CPUTot", cfg_tres.get("cpu", 0)))),
        "cpu_alloc": int(float(record.get("CPUAlloc", alloc_tres.get("cpu", 0)))),
        "mem_total": parse_memory_mb(record.get("RealMemory", "0")),
        "mem_alloc": parse_memory_mb(record.get("AllocMem", "0")),
    }


def parse_nodes(text):
    nodes = []
    for line in text.splitlines():
        if not line.strip():
            continue
        record = parse_node_record(line)
        if record.get("NodeName"):
            nodes.append(build_node(record))
    return nodes


def fetch_nodes(host):
    ssh_cmd = ["ssh", host, "scontrol show nodes --oneliner"]
    result = subprocess.run(
        ssh_cmd,
        shell=False,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "unknown error"
        raise RuntimeError(f"could not read node information from '{host}': {message}")
    return parse_nodes(result.stdout)


def compress_hostlist(names):
    """Collapse node names into Slurm hostlist notation, e.g. gcn[1-3,7]."""
    numbered = OrderedDict()
    plain = []
    for name in names:
        match = TRAILING_NUMBER_RE.match(name)
        if not match:
            plain.append(name)
            continue
        prefix, digits = match.group(1), match.group(2)
        numbered.setdefault((prefix, len(digits)), []).append(int(digits))

    parts = []
    for (prefix, width), numbers in numbered.items():
        ranges = []
        for number in sorted(set(numbers)):
            if ranges and number == ranges[-1][1] + 1:
                ranges[-1][1] = number
            else:
                ranges.append([number, number])
        if len(ranges) == 1 and ranges[0][0] == ranges[0][1]:
            parts.append("{}{:0{}d}".format(prefix, ranges[0][0], width))
        else:
            inner = ",".join(
                "{:0{}d}".format(start, width)
                if start == end
                else "{:0{}d}-{:0{}d}".format(start, width, end, width)
                for start, end in ranges
            )
            parts.append(f"{prefix}[{inner}]")

    return ",".join(parts + plain)


def group_nodes(nodes):
    """Group nodes by partition, partitions with GPUs first."""
    groups = OrderedDict()
    for node in nodes:
        groups.setdefault(node["partitions"], []).append(node)

    def sort_key(item):
        partitions, members = item
        has_gpu = any(node["gpu_total"] for node in members)
        return (0 if has_gpu else 1, partitions)

    return sorted(groups.items(), key=sort_key)


def partition_label(partitions):
    return ",".join(partitions) or "no partition"


def hardware_label(node):
    gpu = f"{node['gpu_total']}x {node['gpu_type'] or 'gpu'}" if node["gpu_total"] else "no GPU"
    return f"{gpu}, {node['cpu_total']} CPU, {format_memory(node['mem_total'])} RAM"


def describe_hardware(nodes):
    """Per-node hardware of a group, listing each kind when the nodes differ."""
    kinds = Counter(hardware_label(node) for node in nodes)
    if len(kinds) == 1:
        return f"{next(iter(kinds))} per node"
    return "; ".join(f"{count}x node with {label}" for label, count in kinds.most_common())


def classify(node):
    if not node["available"]:
        return "unavailable"
    used = node["gpu_alloc"] or node["cpu_alloc"] or node["mem_alloc"]
    if not used:
        return "free"
    gpu_full = node["gpu_total"] > 0 and node["gpu_alloc"] >= node["gpu_total"]
    cpu_full = node["cpu_alloc"] >= node["cpu_total"]
    mem_full = node["mem_alloc"] >= node["mem_total"]
    if gpu_full or cpu_full or mem_full:
        return "full"
    return "partial"


def format_memory(mb):
    if mb >= 1024 ** 2:
        return f"{mb / 1024 ** 2:.1f}T"
    if mb >= 1024:
        return f"{mb / 1024:.0f}G"
    return f"{mb:.0f}M"


def describe_free(node):
    parts = []
    if node["gpu_total"]:
        parts.append(f"{node['gpu_total'] - node['gpu_alloc']}/{node['gpu_total']} GPU")
    parts.append(f"{node['cpu_total'] - node['cpu_alloc']}/{node['cpu_total']} CPU")
    parts.append(
        f"{format_memory(node['mem_total'] - node['mem_alloc'])}/{format_memory(node['mem_total'])} RAM"
    )
    return ", ".join(parts)


def format_group(key, nodes):
    header = f"partition: {partition_label(key)}  |  {describe_hardware(nodes)}"

    buckets = OrderedDict((name, []) for name in ("free", "partial", "full", "unavailable"))
    for node in sorted(nodes, key=lambda n: n["name"]):
        buckets[classify(node)].append(node)

    schedulable = [node for node in nodes if node["available"]]
    free_gpus = sum(node["gpu_total"] - node["gpu_alloc"] for node in schedulable)
    free_cpus = sum(node["cpu_total"] - node["cpu_alloc"] for node in schedulable)
    free_mem = sum(node["mem_total"] - node["mem_alloc"] for node in schedulable)

    lines = [header, "-" * len(header)]

    total_gpus = sum(node["gpu_total"] for node in schedulable)
    total_cpus = sum(node["cpu_total"] for node in schedulable)
    total_mem = sum(node["mem_total"] for node in schedulable)

    available = []
    if any(node["gpu_total"] for node in nodes):
        available.append(f"{free_gpus}/{total_gpus} GPUs")
    available.append(f"{free_cpus}/{total_cpus} CPUs")
    available.append(f"{format_memory(free_mem)}/{format_memory(total_mem)} RAM")
    lines.append("available: " + ", ".join(available))

    counts = ", ".join(f"{len(bucket)} {name}" for name, bucket in buckets.items() if bucket)
    lines.append(f"nodes: {len(nodes)} ({counts})")

    for name in ("free", "full"):
        if buckets[name]:
            lines.append(f"  {name:<10}{compress_hostlist([n['name'] for n in buckets[name]])}")
    for node in buckets["partial"]:
        lines.append(f"  {'partial':<10}{node['name']}  free: {describe_free(node)}")
    for node in buckets["unavailable"]:
        state = "+".join(node["states"]) or "UNKNOWN"
        line = f"  {'down':<10}{node['name']}  {state}"
        if node["reason"]:
            line += f" ({node['reason']})"
        lines.append(line)

    return lines


def format_report(nodes):
    if not nodes:
        return "No nodes found."

    lines = []
    for key, group in group_nodes(nodes):
        lines.extend(format_group(key, group))
        lines.append("")

    schedulable = [node for node in nodes if node["available"]]
    free_gpus = sum(node["gpu_total"] - node["gpu_alloc"] for node in schedulable)
    total_gpus = sum(node["gpu_total"] for node in schedulable)
    free_cpus = sum(node["cpu_total"] - node["cpu_alloc"] for node in schedulable)
    total_cpus = sum(node["cpu_total"] for node in schedulable)
    free_mem = sum(node["mem_total"] - node["mem_alloc"] for node in schedulable)
    total_mem = sum(node["mem_total"] for node in schedulable)

    lines.append(
        "TOTAL available: "
        f"{free_gpus}/{total_gpus} GPUs, "
        f"{free_cpus}/{total_cpus} CPUs, "
        f"{format_memory(free_mem)}/{format_memory(total_mem)} RAM "
        f"across {len(schedulable)}/{len(nodes)} usable nodes"
    )
    return "\n".join(lines)


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    if handle_completion_arguments(args, COMMAND_NAME, parser, COMPLETERS):
        return

    if not args.host:
        parser.error(f"no login node: pass --host or set ${LOGIN_HOST_ENV_VAR}")

    def load():
        nodes = fetch_nodes(args.host)
        if args.partition:
            nodes = [node for node in nodes if args.partition in node["partitions"]]
        return nodes

    try:
        nodes = load()
    except RuntimeError as e:
        print(f"Error: {e}")
        sys.exit(1)

    if not nodes:
        print(f"No nodes found in partition '{args.partition}'." if args.partition else "No nodes found.")
        return

    if args.plain or not sys.stdout.isatty():
        print(format_report(nodes))
        return

    from slurm_utils.tui import run

    run(nodes, args.host, load)


if __name__ == "__main__":
    main()
