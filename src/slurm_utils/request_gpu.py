import argparse
import subprocess
import time
import re
import os
import sys

def parse_args():
    parser = argparse.ArgumentParser(description="Request a GPU node on Snellius and update SSH config.")
    parser.add_argument("--time", type=str, default="01:00:00", help="Job duration (HH:MM:SS), default 1 hour")
    parser.add_argument("--partition", type=str, default="gpu", help="Slurm partition, default 'gpu'")
    parser.add_argument("--gpus", type=str, default="1", help="Number of GPUs, default 1")
    parser.add_argument("--user", type=str, default="spapa01", help="Username on the cluster")
    parser.add_argument("--host", type=str, default="snellius01", help="Login node hostname")
    return parser.parse_args()

def submit_job(args):
    """Submits an interactive-like job that just sleeps."""
    # We need to be careful with quotes when passing commands through SSH.
    # The command roughly becomes: ssh host "sbatch ... --wrap='sleep infinity'"
    # To be safe, we'll wrap the inner command in quotes.
    
    # Construct the sbatch command first
    sbatch_cmd = (
        f"sbatch --parsable "
        f"--partition={args.partition} "
        f"--time={args.time} "
        f"--gpus={args.gpus} "
        f"--wrap='sleep infinity'"
    )
    
    # Now construct the SSH command. We quote the sbatch command to ensure it's treated as a single argument on the remote side if needed,
    # or just rely on proper escaping.
    # Simplest reliable way: pass as a list to subprocess without shell=True, 
    # and pass the entire remote command as one argument to ssh.
    
    ssh_cmd = ["ssh", args.host, sbatch_cmd]
    
    print(f"Submitting job: {' '.join(ssh_cmd)}")
    try:
        # shell=False is safer and cleaner here
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
        # Use a list to separate arguments and avoid shell interpretation of special chars like |
        # We need to wrap the format string in quotes for the remote shell if we were using a string,
        # but with a list, we just pass the argument.
        # However, SSH concatenates arguments with spaces.
        # So we really need to ensure the remote side sees the quotes around the format string.
        # Or better, just don't use characters that need escaping if possible, or quote them.
        
        # ssh args.host "squeue -j job_id -o '%N|%t' --noheader"
        # We will construct the remote command as a single strong string with internal quotes
        
        remote_cmd = f"squeue -j {job_id} -o '%N|%t' --noheader"
        ssh_cmd = ["ssh", args.host, remote_cmd]
        
        try:
            output = subprocess.check_output(ssh_cmd, shell=False).decode().strip()
            if not output:
                print("Job not found in queue (maybe finished or failed?).")
                sys.exit(1)
            
            # Output format: NODE|STATE
            parts = output.split('|')
            if len(parts) < 2:
                 # Sometimes output might be weird if job is just starting or weird state
                 print(f"Unexpected output: {output}")
                 time.sleep(2)
                 continue
                 
            node = parts[0].strip()
            state = parts[1].strip()

            if state == "R":
                print(f"Job is running on node: {node}")
                return node
            elif state in ["PD", "CF", "CG"]: # Pending, Configuring, Completing
                print(f"Job state: {state}. Waiting...")
                time.sleep(5)
            else:
                print(f"Job in unexpected state: {state}")
                if state in ["CD", "F", "TO", "NF"]: # Completed, Failed, Timeout, NodeFail
                    sys.exit(1)
                time.sleep(5)

        except subprocess.CalledProcessError as e:
            print(f"Error checking job status: {e}")
            time.sleep(5)

def update_ssh_config(node_name, proxy_host, user):
    """Updates the ~/.ssh/config file with the new node name. Creates it if missing."""
    config_path = os.path.expanduser("~/.ssh/config")
    
    # Ensure config file exists
    if not os.path.exists(config_path):
        # Create directory if needed
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        # Create empty file
        with open(config_path, "w") as f:
            pass

    with open(config_path, "r") as f:
        lines = f.readlines()
    
    new_lines = []
    in_target_host = False
    target_host_marker = "Host snellius_gpu_node"
    
    found_target = False

    for line in lines:
        stripped_line = line.strip()
        lower_line = stripped_line.lower()

        # Check for start of any block (Host or Match)
        if lower_line.startswith("host ") or lower_line.startswith("match "):
            parts = stripped_line.split()
            # If it's our target Host line
            if lower_line.startswith("host ") and len(parts) >= 2 and "snellius_gpu_node" in parts[1:]:
                in_target_host = True
                found_target = True
                new_lines.append(line)
                # Inject the new HostName right after the Host line
                new_lines.append(f"    HostName {node_name}\n")
                continue
            else:
                in_target_host = False

        if in_target_host:
            # We are inside the target host block. We already injected the new HostName.
            # We skip any existing HostName lines to replace them.
            if lower_line.startswith("hostname ") or lower_line.startswith("hostname=") or lower_line.startswith("hostname\t") or lower_line == "hostname":
                continue
        
        new_lines.append(line)

    if not found_target:
        print(f"'{target_host_marker}' block not found in {config_path}. Adding it.")
        if new_lines and not new_lines[-1].endswith('\n') and new_lines[-1] != '':
            new_lines.append('\n')
        new_lines.append(f"{target_host_marker}\n")
        new_lines.append(f"    HostName {node_name}\n")
        new_lines.append(f"    User {user}\n")
        new_lines.append(f"    ProxyJump {proxy_host}\n")

    with open(config_path, "w") as f:
        f.writelines(new_lines)
    print(f"Updated {config_path} with HostName {node_name}")

def main():
    args = parse_args()
    job_id = submit_job(args)
    node_name = get_job_node(args, job_id)
    update_ssh_config(node_name, args.host, args.user)
    print("Done! You can now access the GPU node via 'ssh snellius_gpu_node'")

if __name__ == "__main__":
    main()
