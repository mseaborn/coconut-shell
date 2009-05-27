
import os
import subprocess
import unittest

import shell
import shell_test

# These tests assume they are run through sudo, though some may still
# pass if not.


class RootShellTests(unittest.TestCase):

    def test_enabling_sudo(self):
        sh = shell.Shell({})
        assert "sudo" in sh.builtins

    def test_normal_command(self):
        sh = shell.Shell({})
        sh.job_controller.shell_to_foreground()
        write_fh, read_fh = shell_test.make_fh_pair()
        sh.run_command("id -u", {1: write_fh, 2: write_fh})
        self.assertEquals(read_fh.read(), os.environ["SUDO_UID"] + "\n")

    def test_setting_groups(self):
        expected_output = subprocess.Popen(
            ["sudo", "-u", "#" + os.environ["SUDO_UID"], "id"],
            stdout=subprocess.PIPE).communicate()[0]
        sh = shell.Shell({})
        sh.job_controller.shell_to_foreground()
        write_fh, read_fh = shell_test.make_fh_pair()
        sh.run_command("id", {1: write_fh, 2: write_fh})
        self.assertEquals(read_fh.read(), expected_output)

    def test_sudo_command(self):
        sh = shell.Shell({})
        sh.job_controller.shell_to_foreground()
        write_fh, read_fh = shell_test.make_fh_pair()
        sh.run_command("sudo id -u", {1: write_fh, 2: write_fh})
        self.assertEquals(read_fh.read(), "0\n")


if __name__ == "__main__":
    unittest.main()
