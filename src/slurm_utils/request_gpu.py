import argparse
import json
import os
import shlex
import subprocess
import sys
import time
from datetime import datetime, timezone

from slurm_utils.cli import (
    DEFAULT_SSH_CONFIG_PATH,
    add_completion_arguments,
    get_config_dir,
    handle_completion_arguments,
    list_ssh_config_hosts,
)
from slurm_utils.completion import FILE, SSH_HOST


COMMAND_NAME = "request-gpu"
LOGIN_HOST_ENV_VAR = "SLURM_LOGIN_HOST"
DEFAULT_SSH_NAME = "slurm_gpu_node"
STATE_FILE_NAME = "request_gpu.json"
COPIED_PROXY_OPTIONS = ("IdentityFile", "IdentitiesOnly")
COMPLETERS = {"--host": SSH_HOST, "--proxy-host": SSH_HOST, "--identity-file": FILE}


def build_parser():
    parser = argparse.ArgumentParser(
        prog=COMMAND_NAME,
        description=(
            "Request a Slurm allocation and update local SSH config. "
            "Pass all sbatch arguments after --."
        ),
    )
    parser.add_argument(
        "--user",
        type=str,
        default=None,
        help="Username on the cluster, default reads the User of the --host SSH config entry",
    )
    parser.add_argument(
        "--host",
        type=str,
        default=os.environ.get(LOGIN_HOST_ENV_VAR),
        help=f"Login node hostname used for sbatch and squeue, default reads ${LOGIN_HOST_ENV_VAR}",
    )
    parser.add_argument(
        "--ssh-name",
        type=str,
        default=None,
        metavar="alias",
        help=f"Local SSH config Host alias, default auto-selects from '{DEFAULT_SSH_NAME}'",
    )
    parser.add_argument(
        "--proxy-host",
        type=str,
        default=None,
        help="ProxyJump host for new SSH config entries, default uses --host",
    )
    parser.add_argument(
        "--identity-file",
        type=str,
        default=None,
        help="IdentityFile to write into the generated SSH config entry",
    )
    parser.add_argument(
        "--email",
        type=str,
        default=None,
        help="Email address to notify when the Slurm job starts running",
    )
    return add_completion_arguments(parser)


def parse_args(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--" in argv:
        separator_index = argv.index("--")
        utility_argv = argv[:separator_index]
        sbatch_args = argv[separator_index + 1:]
    else:
        utility_argv = argv
        sbatch_args = []

    args = build_parser().parse_args(utility_argv)
    args.sbatch_args = sbatch_args
    args.proxy_host = args.proxy_host or args.host
    args.explicit_ssh_name = args.ssh_name is not None
    return args


def resolve_ssh_user(host):
    """Read the username SSH would use for a host from the local SSH config."""
    result = subprocess.run(
        ["ssh", "-G", host],
        shell=False,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode != 0:
        return None

    for line in result.stdout.splitlines():
        keyword, _, value = line.partition(" ")
        if keyword.lower() == "user" and value.strip():
            return value.strip()
    return None


def get_state_path():
    return os.path.join(get_config_dir(), STATE_FILE_NAME)


def load_state(path=None):
    path = path or get_state_path()
    if not os.path.exists(path):
        return {"requests": []}

    try:
        with open(path, "r") as f:
            state = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"requests": []}

    requests = state.get("requests", [])
    if not isinstance(requests, list):
        requests = []
    return {"requests": requests}


def save_state(state, path=None):
    path = path or get_state_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(state, f, indent=2, sort_keys=True)
        f.write("\n")


def is_job_active(login_host, job_id):
    if not login_host or not job_id:
        return False

    remote_cmd = "squeue -j {job_id} --noheader".format(job_id=shlex.quote(str(job_id)))
    result = subprocess.run(
        ["ssh", login_host, remote_cmd],
        shell=False,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode != 0:
        output = f"{result.stdout}\n{result.stderr}".lower()
        if "invalid job id specified" in output or "invalid job id" in output:
            return False
        # Be conservative if the login host is temporarily unavailable.
        return True
    return bool(result.stdout.strip())


def prune_state(state):
    active_requests = []
    for request in state.get("requests", []):
        if is_job_active(request.get("login_host"), request.get("job_id")):
            active_requests.append(request)
    return {"requests": active_requests}


def select_ssh_name(state, requested_name=None):
    active_names = {request.get("ssh_name") for request in state.get("requests", [])}

    if requested_name:
        if requested_name in active_names:
            raise ValueError(f"SSH name '{requested_name}' is already used by an active request")
        return requested_name

    if DEFAULT_SSH_NAME not in active_names:
        return DEFAULT_SSH_NAME

    suffix = 2
    while True:
        candidate = f"{DEFAULT_SSH_NAME}_{suffix}"
        if candidate not in active_names:
            return candidate
        suffix += 1


def record_request(state, job_id, ssh_name, node_name, login_host, proxy_host, identity_file=None):
    requests = list(state.get("requests", []))
    request = {
        "job_id": str(job_id),
        "ssh_name": ssh_name,
        "node_name": node_name,
        "login_host": login_host,
        "proxy_host": proxy_host,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if identity_file:
        request["identity_file"] = identity_file
    requests.append(request)
    return {"requests": requests}


def build_sbatch_command(sbatch_args, email=None):
    quoted_args = [shlex.quote(arg) for arg in sbatch_args]
    mail_args = []
    if email:
        mail_args = [
            shlex.quote(f"--mail-user={email}"),
            "--mail-type=BEGIN",
        ]
    return " ".join(
        ["sbatch", "--parsable", *mail_args, *quoted_args, "--wrap=" + shlex.quote("sleep infinity")]
    )


def submit_job(args):
    """Submits an interactive-like job that just sleeps."""
    sbatch_cmd = build_sbatch_command(args.sbatch_args, args.email)
    ssh_cmd = ["ssh", args.host, sbatch_cmd]

    print(f"Submitting job: {' '.join(ssh_cmd)}")
    try:
        job_id = subprocess.check_output(ssh_cmd, shell=False).decode().strip()
        print(f"Job submitted. ID: {job_id}")
        return job_id
    except subprocess.CalledProcessError as e:
        print(f"Error submitting job: {e}")
        sys.exit(1)


def get_job_node(args, job_id):
    """Waits for the job to start and returns the node name."""
    print("Waiting for job to start...")
    while True:
        remote_cmd = f"squeue -j {shlex.quote(str(job_id))} -o '%N|%t' --noheader"
        ssh_cmd = ["ssh", args.host, remote_cmd]

        try:
            output = subprocess.check_output(ssh_cmd, shell=False).decode().strip()
            if not output:
                print("Job not found in queue (maybe finished or failed?).")
                sys.exit(1)

            parts = output.split("|")
            if len(parts) < 2:
                print(f"Unexpected output: {output}")
                time.sleep(2)
                continue

            node = parts[0].strip()
            state = parts[1].strip()

            if state == "R":
                print(f"Job is running on node: {node}")
                return node
            elif state in ["PD", "CF", "CG"]:
                print(f"Job state: {state}. Waiting...")
                time.sleep(5)
            else:
                print(f"Job in unexpected state: {state}")
                if state in ["CD", "F", "TO", "NF"]:
                    sys.exit(1)
                time.sleep(5)

        except subprocess.CalledProcessError as e:
            print(f"Error checking job status: {e}")
            time.sleep(5)


def get_host_options(lines, host_name):
    options = []
    in_host = False

    for line in lines:
        stripped_line = line.strip()
        lower_line = stripped_line.lower()

        if lower_line.startswith("host ") or lower_line.startswith("match "):
            parts = stripped_line.split()
            in_host = lower_line.startswith("host ") and host_name in parts[1:]
            continue

        if not in_host or not stripped_line or stripped_line.startswith("#"):
            continue

        parts = stripped_line.split(None, 1)
        if len(parts) == 2:
            options.append((parts[0], parts[1]))

    return options


def get_copied_proxy_options(lines, proxy_host):
    copied_option_names = {option.lower() for option in COPIED_PROXY_OPTIONS}
    return [
        (name, value)
        for name, value in get_host_options(lines, proxy_host)
        if name.lower() in copied_option_names
    ]


def get_extra_ssh_options(lines, proxy_host, identity_file=None):
    if identity_file:
        return [("IdentityFile", identity_file), ("IdentitiesOnly", "yes")]
    return get_copied_proxy_options(lines, proxy_host)


def render_ssh_config(lines, ssh_name, node_name, user, proxy_host, extra_options=None):
    extra_options = extra_options or []
    extra_option_names = {option_name.lower() for option_name, _ in extra_options}
    new_lines = []
    in_target_host = False
    found_target = False

    for line in lines:
        stripped_line = line.strip()
        lower_line = stripped_line.lower()

        if lower_line.startswith("host ") or lower_line.startswith("match "):
            parts = stripped_line.split()
            if lower_line.startswith("host ") and ssh_name in parts[1:]:
                in_target_host = True
                found_target = True
                new_lines.append(line)
                new_lines.append(f"    HostName {node_name}\n")
                for option_name, option_value in extra_options:
                    new_lines.append(f"    {option_name} {option_value}\n")
                continue
            in_target_host = False

        option_name = stripped_line.split(None, 1)[0].lower() if stripped_line else ""
        if in_target_host and (option_name == "hostname" or option_name in extra_option_names):
            continue

        new_lines.append(line)

    if not found_target:
        if new_lines and not new_lines[-1].endswith("\n") and new_lines[-1] != "":
            new_lines.append("\n")
        if new_lines and new_lines[-1].strip():
            new_lines.append("\n")
        new_lines.append(f"Host {ssh_name}\n")
        new_lines.append(f"    HostName {node_name}\n")
        new_lines.append(f"    User {user}\n")
        new_lines.append(f"    ProxyJump {proxy_host}\n")
        for option_name, option_value in extra_options:
            new_lines.append(f"    {option_name} {option_value}\n")

    return new_lines, found_target


def update_ssh_config(node_name, proxy_host, user, ssh_name, identity_file=None):
    """Updates the ~/.ssh/config file with the assigned node name. Creates it if missing."""
    config_path = os.path.expanduser(DEFAULT_SSH_CONFIG_PATH)

    if not os.path.exists(config_path):
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        with open(config_path, "w"):
            pass

    with open(config_path, "r") as f:
        lines = f.readlines()

    extra_options = get_extra_ssh_options(lines, proxy_host, identity_file)
    new_lines, found_target = render_ssh_config(lines, ssh_name, node_name, user, proxy_host, extra_options)

    if not found_target:
        print(f"'Host {ssh_name}' block not found in {config_path}. Adding it.")

    with open(config_path, "w") as f:
        f.writelines(new_lines)
    print(f"Updated {config_path}: Host {ssh_name} -> {node_name}")


def main(argv=None):
    args = parse_args(argv)

    if handle_completion_arguments(args, COMMAND_NAME, build_parser(), COMPLETERS):
        return

    if not args.host:
        print(f"Error: no login node. Pass --host or set ${LOGIN_HOST_ENV_VAR}.")
        sys.exit(1)

    user = args.user or resolve_ssh_user(args.host)
    if not user:
        print(f"Error: could not resolve a username for host '{args.host}'. Pass --user explicitly.")
        sys.exit(1)

    state = prune_state(load_state())
    try:
        args.ssh_name = select_ssh_name(state, args.ssh_name)
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)
    save_state(state)

    job_id = submit_job(args)
    node_name = get_job_node(args, job_id)
    update_ssh_config(node_name, args.proxy_host, user, args.ssh_name, args.identity_file)

    state = record_request(
        state,
        job_id,
        args.ssh_name,
        node_name,
        args.host,
        args.proxy_host,
        args.identity_file,
    )
    save_state(state)

    print(f"Done! You can now access the GPU node via 'ssh {args.ssh_name}'")


if __name__ == "__main__":
    main()
