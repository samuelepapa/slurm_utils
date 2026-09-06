import contextlib
import io
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from slurm_utils import request_gpu


def subprocess_result(returncode=0, stdout="", stderr=""):
    return mock.Mock(returncode=returncode, stdout=stdout, stderr=stderr)


class RequestGpuTests(unittest.TestCase):
    def test_parse_forwards_sbatch_args_after_separator(self):
        args = request_gpu.parse_args(
            [
                "--host",
                "login",
                "--",
                "--partition=gpu",
                "--time=02:00:00",
                "--gres=gpu:2",
                "-n",
                "1",
                "--cpus-per-task=8",
            ]
        )

        self.assertEqual(args.host, "login")
        self.assertEqual(
            args.sbatch_args,
            [
                "--partition=gpu",
                "--time=02:00:00",
                "--gres=gpu:2",
                "-n",
                "1",
                "--cpus-per-task=8",
            ],
        )

    def test_parse_rejects_slurm_args_before_separator(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                request_gpu.parse_args(["--time", "02:00:00"])

    def test_parse_proxy_host_defaults_to_login_host(self):
        args = request_gpu.parse_args(["--host", "login"])

        self.assertEqual(args.proxy_host, "login")

    def test_parse_proxy_host_override(self):
        args = request_gpu.parse_args(["--host", "login", "--proxy-host", "proxy"])

        self.assertEqual(args.proxy_host, "proxy")

    def test_parse_identity_file(self):
        args = request_gpu.parse_args(["--identity-file", "~/.ssh/id_custom"])

        self.assertEqual(args.identity_file, "~/.ssh/id_custom")

    def test_parse_email(self):
        args = request_gpu.parse_args(["--email", "user@example.com", "--", "--partition=gpu"])

        self.assertEqual(args.email, "user@example.com")
        self.assertEqual(args.sbatch_args, ["--partition=gpu"])

    def test_build_sbatch_command_has_no_slurm_defaults(self):
        command = request_gpu.build_sbatch_command([])

        self.assertEqual(command, "sbatch --parsable --wrap='sleep infinity'")
        self.assertNotIn("--partition", command)
        self.assertNotIn("--time", command)
        self.assertNotIn("--gpus", command)
        self.assertNotIn("--gres", command)

    def test_build_sbatch_command_quotes_forwarded_args(self):
        command = request_gpu.build_sbatch_command(["--gres=gpu:2", "--comment=needs space"])

        self.assertEqual(
            command,
            "sbatch --parsable --gres=gpu:2 '--comment=needs space' --wrap='sleep infinity'",
        )

    def test_build_sbatch_command_adds_start_email_notification(self):
        command = request_gpu.build_sbatch_command([], "user@example.com")

        self.assertEqual(
            command,
            "sbatch --parsable --mail-user=user@example.com --mail-type=BEGIN --wrap='sleep infinity'",
        )

    def test_select_ssh_name_uses_numbered_aliases(self):
        state = {
            "requests": [
                {"ssh_name": "snellius_gpu_node"},
                {"ssh_name": "snellius_gpu_node_2"},
            ]
        }

        self.assertEqual(request_gpu.select_ssh_name(state), "snellius_gpu_node_3")

    def test_select_ssh_name_rejects_explicit_active_alias(self):
        state = {"requests": [{"ssh_name": "custom_gpu"}]}

        with self.assertRaisesRegex(ValueError, "already used"):
            request_gpu.select_ssh_name(state, "custom_gpu")

    def test_prune_state_drops_inactive_jobs(self):
        state = {
            "requests": [
                {"job_id": "1", "login_host": "login", "ssh_name": "a"},
                {"job_id": "2", "login_host": "login", "ssh_name": "b"},
            ]
        }

        with mock.patch.object(request_gpu, "is_job_active", side_effect=[True, False]):
            pruned = request_gpu.prune_state(state)

        self.assertEqual(pruned, {"requests": [{"job_id": "1", "login_host": "login", "ssh_name": "a"}]})

    def test_is_job_active_treats_invalid_job_id_as_inactive(self):
        result = subprocess_result(
            returncode=1,
            stderr="slurm_load_jobs error: Invalid job id specified\n",
        )

        with mock.patch.object(request_gpu.subprocess, "run", return_value=result):
            self.assertFalse(request_gpu.is_job_active("login", "123"))

    def test_is_job_active_keeps_entry_on_ssh_failure(self):
        result = subprocess_result(returncode=255, stderr="ssh: Could not resolve hostname login\n")

        with mock.patch.object(request_gpu.subprocess, "run", return_value=result):
            self.assertTrue(request_gpu.is_job_active("login", "123"))

    def test_render_ssh_config_updates_existing_host_name(self):
        lines = [
            "Host snellius_gpu_node\n",
            "    HostName oldnode\n",
            "    User spapa01\n",
            "    ProxyJump snellius01\n",
        ]

        rendered, found = request_gpu.render_ssh_config(
            lines, "snellius_gpu_node", "newnode", "spapa01", "proxy"
        )

        self.assertTrue(found)
        self.assertEqual(
            rendered,
            [
                "Host snellius_gpu_node\n",
                "    HostName newnode\n",
                "    User spapa01\n",
                "    ProxyJump snellius01\n",
            ],
        )

    def test_render_ssh_config_updates_existing_identity_file(self):
        lines = [
            "Host gpu_2\n",
            "    HostName oldnode\n",
            "    User user\n",
            "    ProxyJump proxy\n",
            "    IdentityFile ~/.ssh/old_key\n",
            "    IdentitiesOnly no\n",
        ]

        rendered, found = request_gpu.render_ssh_config(
            lines,
            "gpu_2",
            "node2",
            "user",
            "proxy",
            [("IdentityFile", "~/.ssh/new_key"), ("IdentitiesOnly", "yes")],
        )

        self.assertTrue(found)
        self.assertEqual(
            rendered,
            [
                "Host gpu_2\n",
                "    HostName node2\n",
                "    IdentityFile ~/.ssh/new_key\n",
                "    IdentitiesOnly yes\n",
                "    User user\n",
                "    ProxyJump proxy\n",
            ],
        )

    def test_render_ssh_config_appends_missing_host(self):
        rendered, found = request_gpu.render_ssh_config([], "gpu_2", "node2", "user", "proxy")

        self.assertFalse(found)
        self.assertEqual(
            rendered,
            [
                "Host gpu_2\n",
                "    HostName node2\n",
                "    User user\n",
                "    ProxyJump proxy\n",
            ],
        )

    def test_get_copied_proxy_options_reads_auth_options(self):
        lines = [
            "Host hipster\n",
            "  HostName hipster.science.uva.nl\n",
            "  User spapa\n",
            "  IdentityFile ~/.ssh/id_rsa_cuteandcuter\n",
            "  IdentitiesOnly yes\n",
            "  ForwardAgent yes\n",
        ]

        self.assertEqual(
            request_gpu.get_copied_proxy_options(lines, "hipster"),
            [
                ("IdentityFile", "~/.ssh/id_rsa_cuteandcuter"),
                ("IdentitiesOnly", "yes"),
            ],
        )

    def test_render_ssh_config_appends_extra_options(self):
        rendered, found = request_gpu.render_ssh_config(
            [],
            "gpu_2",
            "node2",
            "user",
            "proxy",
            [("IdentityFile", "~/.ssh/id_rsa_cuteandcuter"), ("IdentitiesOnly", "yes")],
        )

        self.assertFalse(found)
        self.assertEqual(
            rendered,
            [
                "Host gpu_2\n",
                "    HostName node2\n",
                "    User user\n",
                "    ProxyJump proxy\n",
                "    IdentityFile ~/.ssh/id_rsa_cuteandcuter\n",
                "    IdentitiesOnly yes\n",
            ],
        )

    def test_get_extra_ssh_options_prefers_explicit_identity_file(self):
        lines = [
            "Host proxy\n",
            "  IdentityFile ~/.ssh/proxy_key\n",
            "  IdentitiesOnly yes\n",
        ]

        self.assertEqual(
            request_gpu.get_extra_ssh_options(lines, "proxy", "~/.ssh/custom_key"),
            [("IdentityFile", "~/.ssh/custom_key"), ("IdentitiesOnly", "yes")],
        )

    def test_record_request_includes_identity_file_when_set(self):
        state = request_gpu.record_request(
            {"requests": []},
            "1",
            "gpu_2",
            "node2",
            "login",
            "proxy",
            "~/.ssh/custom_key",
        )

        self.assertEqual(state["requests"][0]["identity_file"], "~/.ssh/custom_key")


if __name__ == "__main__":
    unittest.main()
