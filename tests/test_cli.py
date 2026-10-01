import argparse
import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from slurm_utils import cli, completion, request_gpu, resources


def write_config(directory, name, content):
    path = os.path.join(directory, name)
    with open(path, "w") as f:
        f.write(content)
    return path


COMMANDS = (
    (request_gpu.COMMAND_NAME, request_gpu.build_parser(), request_gpu.COMPLETERS),
    (resources.COMMAND_NAME, resources.build_parser(), resources.COMPLETERS),
)


class SshConfigTests(unittest.TestCase):
    def test_list_ssh_config_hosts_skips_patterns_and_keeps_order(self):
        with tempfile.TemporaryDirectory() as directory:
            path = write_config(
                directory,
                "config",
                "# comment\n"
                "Host snellius01 snellius02\n"
                "  User spapa01\n"
                "Host *\n"
                "  ForwardAgent yes\n"
                "Host gpu_?\n"
                "Match host hipster\n"
                "  User spapa\n"
                "Host hipster\n",
            )

            self.assertEqual(
                cli.list_ssh_config_hosts(path),
                ["snellius01", "snellius02", "hipster"],
            )

    def test_list_ssh_config_hosts_follows_includes(self):
        with tempfile.TemporaryDirectory() as directory:
            write_config(directory, "work.conf", "Host work_login\n  User worker\n")
            path = write_config(directory, "config", "Include work.conf\nHost personal\n")

            self.assertEqual(cli.list_ssh_config_hosts(path), ["work_login", "personal"])

    def test_list_ssh_config_hosts_survives_include_cycles(self):
        with tempfile.TemporaryDirectory() as directory:
            write_config(directory, "a.conf", "Include config\nHost from_a\n")
            path = write_config(directory, "config", "Include a.conf\nHost from_config\n")

            self.assertEqual(cli.list_ssh_config_hosts(path), ["from_a", "from_config"])

    def test_list_ssh_config_hosts_returns_empty_without_config(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(cli.list_ssh_config_hosts(os.path.join(directory, "missing")), [])


class CompletionRenderingTests(unittest.TestCase):
    def test_scripts_cover_every_option_of_every_command(self):
        for prog, parser, completers in COMMANDS:
            options = {
                option for action in parser._actions for option in action.option_strings
            }
            for shell in completion.SHELLS:
                script = completion.render_completion_script(shell, prog, parser, completers)
                for option in options:
                    self.assertIn(option, script, f"{option} missing from {prog} {shell}")

    def test_scripts_are_named_after_the_command(self):
        for prog, parser, completers in COMMANDS:
            for shell in completion.SHELLS:
                script = completion.render_completion_script(shell, prog, parser, completers)

                self.assertIn(completion.function_name(prog), script)
                self.assertIn(f"{prog} --list-ssh-hosts", script)

    def test_option_specs_classify_by_parser_and_completers(self):
        parser = argparse.ArgumentParser(add_help=True)
        parser.add_argument("--host")
        parser.add_argument("--key")
        parser.add_argument("--name")
        parser.add_argument("--verbose", action="store_true")
        parser.add_argument("--shell", choices=("bash", "zsh"))

        specs = {
            spec["flags"][0]: spec["completer"]
            for spec in completion.option_specs(
                parser, {"--host": completion.SSH_HOST, "--key": completion.FILE}
            )
        }

        self.assertEqual(specs["--host"], completion.SSH_HOST)
        self.assertEqual(specs["--key"], completion.FILE)
        self.assertEqual(specs["--name"], completion.VALUE)
        self.assertEqual(specs["--verbose"], completion.FLAG)
        self.assertEqual(specs["--shell"], completion.CHOICES)
        self.assertEqual(specs["-h"], completion.HELP)

    def test_bash_script_groups_flags_by_completer(self):
        prog, parser, completers = COMMANDS[0]
        script = completion.render_completion_script("bash", prog, parser, completers)

        self.assertIn("--host|--proxy-host)", script)
        self.assertIn("--identity-file)", script)
        self.assertIn('COMPREPLY=($(compgen -W "bash zsh" -- "$cur"))', script)

    def test_zsh_script_omits_ssh_host_block_without_ssh_host_options(self):
        parser = argparse.ArgumentParser()
        parser.add_argument("--name")

        script = completion.render_completion_script("zsh", "demo", parser)

        self.assertNotIn("ssh_hosts", script)
        self.assertIn("'--name[]:name:'", script)

    def test_zsh_descriptions_are_escaped(self):
        parser = argparse.ArgumentParser(add_help=False)
        parser.add_argument("--tricky", help="uses [brackets] and: colons")

        script = completion.render_completion_script("zsh", "demo", parser)

        self.assertIn("uses \\[brackets\\] and\\: colons", script)

    def test_generated_scripts_are_syntactically_valid(self):
        for shell in ("bash", "zsh"):
            binary = f"/bin/{shell}" if shell == "bash" else "/bin/zsh"
            if not os.path.exists(binary):
                continue
            for prog, parser, completers in COMMANDS:
                script = completion.render_completion_script(shell, prog, parser, completers)
                result = subprocess.run(
                    [binary, "-n"], input=script, text=True, capture_output=True
                )
                self.assertEqual(result.returncode, 0, f"{prog} {shell}: {result.stderr}")


class InstallCompletionTests(unittest.TestCase):
    def test_writes_script_and_sources_it(self):
        prog, parser, completers = COMMANDS[0]
        with tempfile.TemporaryDirectory() as home:
            config_dir = os.path.join(home, ".config", "slurm_utils")

            script_path, rc_path, already_sourced = completion.install_completion(
                "zsh", prog, parser, config_dir, completers, home=home
            )

            self.assertFalse(already_sourced)
            self.assertEqual(rc_path, os.path.join(home, ".zshrc"))
            with open(script_path) as f:
                self.assertEqual(
                    f.read(),
                    completion.render_completion_script("zsh", prog, parser, completers),
                )
            with open(rc_path) as f:
                self.assertIn(f'source "{script_path}"', f.read())

    def test_is_idempotent(self):
        prog, parser, _ = COMMANDS[0]
        with tempfile.TemporaryDirectory() as home:
            config_dir = os.path.join(home, ".config", "slurm_utils")
            completion.install_completion("bash", prog, parser, config_dir, home=home)

            _, rc_path, already_sourced = completion.install_completion(
                "bash", prog, parser, config_dir, home=home
            )

            self.assertTrue(already_sourced)
            with open(rc_path) as f:
                self.assertEqual(f.read().count("source"), 1)

    def test_commands_do_not_share_a_script_file(self):
        with tempfile.TemporaryDirectory() as home:
            config_dir = os.path.join(home, "cfg")
            paths = {
                completion.install_completion("bash", prog, parser, config_dir, c, home=home)[0]
                for prog, parser, c in COMMANDS
            }

            self.assertEqual(len(paths), len(COMMANDS))

    def test_prefers_an_existing_bash_profile(self):
        prog, parser, _ = COMMANDS[0]
        with tempfile.TemporaryDirectory() as home:
            write_config(home, ".bash_profile", "# login shell\n")

            _, rc_path, _ = completion.install_completion(
                "bash", prog, parser, os.path.join(home, "cfg"), home=home
            )

            self.assertEqual(rc_path, os.path.join(home, ".bash_profile"))


class CompletionArgumentTests(unittest.TestCase):
    def test_every_command_installs_its_own_completion(self):
        for module in (request_gpu, resources):
            output = io.StringIO()
            with tempfile.TemporaryDirectory() as home:
                config_dir = os.path.join(home, "cfg")
                with mock.patch.dict(os.environ, {"ZDOTDIR": home}):
                    with mock.patch.object(cli, "get_config_dir", return_value=config_dir):
                        with contextlib.redirect_stdout(output):
                            module.main(["--setup-completion", "zsh"])

                script_path = os.path.join(
                    config_dir, f"completion.{module.COMMAND_NAME}.zsh"
                )
                self.assertTrue(os.path.exists(script_path))

    def test_every_command_lists_ssh_hosts(self):
        for module in (request_gpu, resources):
            output = io.StringIO()
            with mock.patch.object(cli, "list_ssh_config_hosts", return_value=["a", "b"]):
                with contextlib.redirect_stdout(output):
                    module.main(["--list-ssh-hosts"])

            self.assertEqual(output.getvalue(), "a\nb\n")


if __name__ == "__main__":
    unittest.main()
