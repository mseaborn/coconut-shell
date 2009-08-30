
# Copyright (C) 2008 Mark Seaborn
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA
# 02110-1301 USA.

import errno
import os
import signal
import subprocess
import sys
import tempfile
import unittest

import pyparsing as parse

import jobcontrol
import shell
import tempdir_test


def make_fh_pair():
    # Make read/write file handle pair.  This is like creating a pipe
    # FD pair, but without a pipe buffer limit.
    fd, filename = tempfile.mkstemp(prefix="shell_test_")
    try:
        write_fh = os.fdopen(fd, "w", 0)
        read_fh = open(filename, "r")
    finally:
        os.unlink(filename)
    return write_fh, read_fh


def read_file(filename):
    fh = open(filename, "r")
    try:
        return fh.read()
    finally:
        fh.close()


def write_file(filename, data):
    fh = open(filename, "w")
    try:
        fh.write(data)
    finally:
        fh.close()


def set_env_var(key, value):
    if value is None:
        del os.environ[key]
    else:
        os.environ[key] = value


def pop_all(a_list):
    copy = a_list[:]
    a_list[:] = []
    return copy


def std_fds(stdin, stdout, stderr):
    return {0: stdin, 1: stdout, 2: stderr}

def default_fds():
    return {0: sys.stdin, 1: sys.stdout, 2: sys.stderr}


def make_shell(parts=None):
    if parts is None:
        parts = {}
    parts["job_spawner"] = jobcontrol.SimpleJobSpawner()
    return shell.Shell(parts)


def run_command(command, fds):
    make_shell().run_command(command, fds)


class TestCase(tempdir_test.TempDirTestCase):

    def patch_env_var(self, key, value):
        old_value = os.environ.get(key)
        set_env_var(key, value)
        self.on_teardown(lambda: set_env_var(key, old_value))


class ShellTests(TestCase):

    def command_output(self, command):
        write_stdout, read_stdout = make_fh_pair()
        write_stderr, read_stderr = make_fh_pair()
        run_command(command,
                    std_fds(stdin=open(os.devnull, "r"),
                            stdout=write_stdout, stderr=write_stderr))
        self.assertEquals(read_stderr.read(), "")
        return read_stdout.read()

    def test_simple(self):
        data = self.command_output('echo foo "bar baz"')
        self.assertEquals(data, "foo bar baz\n")

    def test_quoting(self):
        data = self.command_output("echo foo  'bar  baz' ''")
        self.assertEquals(data, "foo bar  baz \n")

    def test_punctuation(self):
        data = self.command_output('echo . +')
        self.assertEquals(data, ". +\n")

    def test_pipeline(self):
        data = self.command_output(
            "echo foo | sh -c 'echo open && cat && echo close'")
        self.assertEquals(data, "open\nfoo\nclose\n")

    def test_empty_command(self):
        data = self.command_output("")
        self.assertEquals(data, "")

    def test_breaking_pipe(self):
        # "yes" should exit because its pipe is broken.
        data = self.command_output("yes | echo done")
        self.assertEquals(data, "done\n")

    def test_syntax_error(self):
        self.assertRaises(parse.ParseException,
                          lambda: self.command_output('echo \000'))

    def test_command_not_found(self):
        write_stdout, read_stdout = make_fh_pair()
        write_stderr, read_stderr = make_fh_pair()
        run_command("made-up-command-123 arg1 arg2",
                    std_fds(stdin=open(os.devnull, "r"),
                            stdout=write_stdout, stderr=write_stderr))
        self.assertEquals(read_stdout.read(), "")
        self.assertEquals(read_stderr.read(),
                          "made-up-command-123: command not found\n")

    def test_globbing(self):
        temp_dir = self.make_temp_dir()
        write_file(os.path.join(temp_dir, "aaa"), "")
        write_file(os.path.join(temp_dir, "aab"), "")
        write_file(os.path.join(temp_dir, "bbb"), "")
        os.chdir(temp_dir)
        data = self.command_output("echo a*")
        self.assertEquals(data, "aaa aab\n")

    def test_globbing_no_match(self):
        os.chdir(self.make_temp_dir())
        # Glob expressions that match nothing return the glob
        # expression, as is the default in Bash.  This is more useful
        # in interactive mode than returning nothing (which is more
        # useful in programs).
        data = self.command_output("echo *.txt")
        self.assertEquals(data, "*.txt\n")

    def test_chdir(self):
        temp_dir = self.make_temp_dir()
        output = self.command_output("cd / %s" % temp_dir)
        self.assertEquals(output, "")
        self.assertEquals(os.getcwd(), os.path.realpath(temp_dir))

    def test_chdir_home_dir(self):
        home_dir = self.make_temp_dir()
        self.patch_env_var("HOME", home_dir)
        os.chdir(self.make_temp_dir())
        output = self.command_output("cd")
        self.assertEquals(output, "")
        self.assertEquals(os.getcwd(), os.path.realpath(home_dir))

    def test_tilde_expansion(self):
        home_dir = "/my/home/town"
        self.patch_env_var("HOME", home_dir)
        output = self.command_output("echo ~")
        self.assertEquals(output, home_dir + "\n")
        output = self.command_output("echo ~/foo")
        self.assertEquals(output, home_dir + "/foo\n")
        # If HOME is unset, os.path.expanduser() looks at /etc/passwd,
        # but that is inconsistent with the fallback for "cd", which
        # is to give an error.

    def test_tilde_expansion_in_file_redirection(self):
        home_dir = self.make_temp_dir()
        write_file(os.path.join(home_dir, "foo"), "quux")
        self.patch_env_var("HOME", home_dir)
        output = self.command_output("cat < ~/foo")
        self.assertEquals(output, "quux")

    def test_tilde_unexpansion(self):
        home_dir = "/my/home/town"
        self.patch_env_var("HOME", home_dir)
        self.assertEquals(shell.unexpanduser("/my/home/town/village/idiot"),
                          "~/village/idiot")
        self.assertEquals(shell.unexpanduser("/shelbyville"),
                          "/shelbyville")

    def test_get_logical_cwd(self):
        cwd_tracker = make_shell().cwd
        temp_dir = self.make_temp_dir()
        os.mkdir(os.path.join(temp_dir, "realdir"))
        os.symlink("realdir", os.path.join(temp_dir, "symlink"))
        physical_path = os.path.join(temp_dir, "realdir")
        logical_path = os.path.join(temp_dir, "symlink")
        cwd_tracker.chdir(logical_path)
        self.assertEquals(cwd_tracker.get_cwd(), logical_path)
        # Should also work when PWD is unset, pointing to the wrong
        # directory, or pointing to a nonexistent path.
        del os.environ["PWD"]
        self.assertEquals(cwd_tracker.get_cwd(), physical_path)
        os.environ["PWD"] = "/"
        self.assertEquals(cwd_tracker.get_cwd(), physical_path)
        os.environ["PWD"] = "/does/not/exist"
        self.assertEquals(cwd_tracker.get_cwd(), physical_path)

    def test_logical_chdir(self):
        cwd_tracker = make_shell().cwd
        temp_dir = self.make_temp_dir()
        os.makedirs(os.path.join(temp_dir, "realdir", "subdir"))
        os.symlink("realdir", os.path.join(temp_dir, "symlink"))
        logical_path = os.path.join(temp_dir, "symlink")
        cwd_tracker.chdir(logical_path)
        cwd_tracker.chdir("subdir")
        self.assertEquals(cwd_tracker.get_cwd(),
                          os.path.join(logical_path, "subdir"))

    def test_chdir_to_parent(self):
        cwd_tracker = make_shell().cwd
        dir_path1 = self.make_temp_dir()
        dir_path2 = os.path.join(dir_path1, "dir2")
        os.mkdir(dir_path2)
        cwd_tracker.chdir(dir_path2 + "/")
        self.assertEquals(cwd_tracker.get_cwd(), dir_path2)
        cwd_tracker.chdir("..")
        self.assertEquals(cwd_tracker.get_cwd(), dir_path1)

    def test_get_prompt_in_deleted_directory(self):
        temp_dir = self.make_temp_dir()
        path = os.path.join(temp_dir, "dir2")
        os.mkdir(path)
        os.chdir(path)
        os.rmdir(path)
        make_shell().get_prompt()

    def test_completion(self):
        temp_dir = self.make_temp_dir()
        os.mkdir(os.path.join(temp_dir, "a-dir"))
        os.mkdir(os.path.join(temp_dir, "b-dir"))
        write_file(os.path.join(temp_dir, "a-file"), "")
        os.chdir(temp_dir)
        self.assertEquals(sorted(shell.complete_filename("a-")),
                          ["a-dir/", "a-file"])

    def test_completion_with_tilde_expansion(self):
        home_dir = self.make_temp_dir()
        self.patch_env_var("HOME", home_dir)
        os.mkdir(os.path.join(home_dir, "a-dir"))
        os.mkdir(os.path.join(home_dir, "b-dir"))
        # Recent versions of Bash expand out ~ when doing completion,
        # but we leave the ~ in place, which I prefer.
        self.assertEquals(list(shell.complete_filename("~/a-")),
                          ["~/a-dir/"])

    def test_completion_of_command_names(self):
        bin_dir1 = self.make_temp_dir()
        bin_dir2 = self.make_temp_dir()
        path = ":".join([bin_dir1, bin_dir2])
        write_file(os.path.join(bin_dir1, "program1"), "")
        write_file(os.path.join(bin_dir2, "program2"), "")
        os.symlink("does-not-exist", os.path.join(bin_dir1, "dangling-link"))
        # Non-executable files are not listed.
        self.assertEquals(list(shell.complete_path_command(path, "")), [])
        os.chmod(os.path.join(bin_dir1, "program1"), 0555)
        os.chmod(os.path.join(bin_dir2, "program2"), 0555)
        self.assertEquals(list(shell.complete_path_command(path, "")),
                          ["program1", "program2"])

        self.patch_env_var("PATH", path)
        # Both files and commands can be listed by completion.
        current_dir = self.make_temp_dir()
        write_file(os.path.join(current_dir, "file"), "")
        os.chdir(current_dir)
        completer = make_shell().completer
        self.assertEquals(completer("  ", ""),
                          ["file", "program1", "program2"])
        self.assertEquals(completer("cmd", ""),
                          ["file"])

    def test_filename_completion_with_trailing_slash(self):
        test_dir = self.make_temp_dir()
        write_file(os.path.join(test_dir, "foo-file"), "")
        sh = make_shell()
        # Preserving trailing slashes when completing is important
        # because pyrepl's completion will not remove characters.
        self.assertEquals(sh.completer("cmd", test_dir + "///"),
                          [test_dir + "///" + "foo-file"])

    def test_command_completion_with_trailing_slash(self):
        bin_dir = self.make_temp_dir()
        write_file(os.path.join(bin_dir, "program1"), "")
        os.chmod(os.path.join(bin_dir, "program1"), 0555)
        sh = make_shell({"environ": {"PATH": bin_dir + "/"},
                         "real_cwd": shell.LocalCwdTracker()})
        sh.real_cwd.chdir(self.make_temp_dir())
        self.assertEquals(sh.completer("", ""), ["program1"])

    def test_completion_on_non_existent_directory(self):
        empty_dir = self.make_temp_dir()
        sh = make_shell({"environ": {"PATH": empty_dir},
                         "real_cwd": shell.LocalCwdTracker()})
        sh.real_cwd.chdir(empty_dir)
        self.assertEquals(sh.completer("", "foo/"), [])

    def test_fds_not_leaked(self):
        data = self.command_output("ls /proc/self/fd")
        # FD 3 is the directory FD opened to list the directory.
        self.assertEquals(data, "0\n1\n2\n3\n")

    def test_fd_setting(self):
        write_fd, read_fd = make_fh_pair()
        fds = {123: write_fd}
        run_command("bash -c 'echo hello >&123'", fds)
        self.assertEquals(read_fd.read(), "hello\n")

    def test_fd_setting_with_swapping(self):
        write_fd1, read_fd1 = make_fh_pair()
        write_fd2, read_fd2 = make_fh_pair()
        fds = {write_fd1.fileno(): write_fd2,
               write_fd2.fileno(): write_fd1}
        command = "bash -c 'echo foo >&%i; echo bar >&%i'" % (
            write_fd1.fileno(), write_fd2.fileno())
        run_command(command, fds)
        self.assertEquals(read_fd2.read(), "foo\n")
        self.assertEquals(read_fd1.read(), "bar\n")

    def test_fd_redirection_stdout(self):
        write_fd, read_fd = make_fh_pair()
        run_command("echo hello >& 123", {123: write_fd})
        self.assertEquals(read_fd.read(), "hello\n")

    def test_fd_redirection_stdin(self):
        write_fd1, read_fd1 = make_fh_pair()
        write_fd2, read_fd2 = make_fh_pair()
        write_fd1.write("supercow powers")
        write_fd1.close()
        run_command("cat <& 123", {123: read_fd1, 1: write_fd2})
        self.assertEquals(read_fd2.read(), "supercow powers")

    def test_not_a_redirection(self):
        temp_file = os.path.join(self.make_temp_dir(), "file")
        data = self.command_output("echo foo 42 >%s" % temp_file)
        self.assertEquals(data, "")
        self.assertEquals(read_file(temp_file), "foo 42\n")

    def test_environ(self):
        sh = shell.Shell({"job_spawner": jobcontrol.SimpleJobSpawner(),
                          "environ": {"FOO123": "bar1234",
                                      "PATH": os.environ["PATH"]}})
        write_stdout, read_stdout = make_fh_pair()
        sh.run_command("printenv FOO123", {1: write_stdout, 2: sys.stderr})
        self.assertEquals(read_stdout.read(), "bar1234\n")


class FDRedirectionTests(tempdir_test.TempDirTestCase):

    def fds_for_command(self, command, fds):
        fds_got = []
        class DummyLauncher(object):
            def spawn(self2, job, spec):
                self.assertEquals(spec["args"], ["foo"])
                fds_got.append(spec["fds"])

        job_spawner = None
        shell.run_command(job_spawner, DummyLauncher(), command,
                          {"fds": fds, "cwd": shell.GlobalCwdTracker()})
        self.assertEquals(len(fds_got), 1)
        return fds_got[0]

    def test_stdin_from_file(self):
        temp_dir = self.make_temp_dir()
        write_file(os.path.join(temp_dir, "file"), "")
        os.chdir(temp_dir)
        fds = self.fds_for_command("foo <file", {})
        self.assertEquals(fds.keys(), [0])
        self.assertEquals(fds[0].mode, "r")

    def test_any_from_file(self):
        temp_dir = self.make_temp_dir()
        write_file(os.path.join(temp_dir, "file"), "")
        os.chdir(temp_dir)
        fds = self.fds_for_command("foo 123<file", {})
        self.assertEquals(fds.keys(), [123])
        self.assertEquals(fds[123].mode, "r")

    def test_stdout_to_file(self):
        temp_dir = self.make_temp_dir()
        os.chdir(temp_dir)
        fds = self.fds_for_command("foo >file", {})
        self.assertEquals(fds.keys(), [1])
        self.assertEquals(fds[1].mode, "w")
        assert os.path.exists(os.path.join(temp_dir, "file"))

    def test_any_to_file(self):
        temp_dir = self.make_temp_dir()
        os.chdir(temp_dir)
        fds = self.fds_for_command("foo 123>file", {})
        self.assertEquals(fds.keys(), [123])
        self.assertEquals(fds[123].mode, "w")
        assert os.path.exists(os.path.join(temp_dir, "file"))

    def test_stdin_to_fd(self):
        fd = open(os.devnull)
        fds = self.fds_for_command("foo <& 123", {123: fd})
        self.assertEquals(sorted(fds.keys()), [0, 123])
        self.assertEquals(fds[0], fd)

    def test_stdout_to_fd(self):
        fd = open(os.devnull)
        fds = self.fds_for_command("foo >& 123", {123: fd})
        self.assertEquals(sorted(fds.keys()), [1, 123])
        self.assertEquals(fds[1], fd)

    def test_any_to_fd_1(self):
        fd = open(os.devnull)
        fds = self.fds_for_command("foo 45>& 123", {123: fd})
        self.assertEquals(sorted(fds.keys()), [45, 123])
        self.assertEquals(fds[45], fd)

    def test_any_to_fd_2(self):
        fd = open(os.devnull)
        fds = self.fds_for_command("foo 45<& 123", {123: fd})
        self.assertEquals(sorted(fds.keys()), [45, 123])
        self.assertEquals(fds[45], fd)

    def test_file_open_error(self):
        # TODO: Handle this nicely.
        self.assertRaises(
            IOError, lambda: self.fds_for_command("foo </does/not/exist", {}))

    def test_bad_fd_error(self):
        # TODO: Handle this properly.  Either don't start any part of
        # the job at all, or record it in the jobs list properly.
        self.assertRaises(KeyError,
                          lambda: self.fds_for_command("foo >&123", {}))


class CommandLineEntryPointTest(tempdir_test.TempDirTestCase):

    def test_non_interactive(self):
        proc = subprocess.Popen(["python", shell.__file__, "-c", "echo hello"],
                                stdin=open(os.devnull, "w"),
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = proc.communicate()
        self.assertEquals((proc.wait(), stdout, stderr),
                          (0, "hello\n", ""))


class IndependentCwdTests(tempdir_test.TempDirTestCase):

    def test_cwd_tracker(self):
        dir1 = self.make_temp_dir()
        dir2 = self.make_temp_dir()
        tracker1 = shell.LocalCwdTracker()
        tracker2 = shell.LocalCwdTracker()
        tracker1.chdir(dir1)
        tracker2.chdir(dir2)
        self.assertEquals(tracker1.get_cwd(), dir1)
        self.assertEquals(tracker2.get_cwd(), dir2)
        tracker1.get_stat()

    def make_shell(self):
        return shell.Shell({"real_cwd": shell.LocalCwdTracker(),
                            "job_spawner": jobcontrol.SimpleJobSpawner()})

    def test_independent_cwds(self):
        shell1 = self.make_shell()
        shell2 = self.make_shell()
        dir1 = self.make_temp_dir()
        dir2 = self.make_temp_dir()
        shell1.run_command("cd %s" % dir1, default_fds())
        shell2.run_command("cd %s" % dir2, default_fds())

        write_stdout, read_stdout = make_fh_pair()
        shell1.run_command("pwd", {1: write_stdout, 2: sys.stderr})
        self.assertEquals(read_stdout.read(), "%s\n" % dir1)

        write_stdout, read_stdout = make_fh_pair()
        shell2.run_command("pwd", {1: write_stdout, 2: sys.stderr})
        self.assertEquals(read_stdout.read(), "%s\n" % dir2)

    def test_cwd_relative_chdir(self):
        temp_dir = self.make_temp_dir()
        os.mkdir(os.path.join(temp_dir, "foo123456"))
        sh = self.make_shell()
        sh.run_command("cd %s" % temp_dir, default_fds())
        sh.run_command("cd foo123456", default_fds())
        self.assertEquals(sh.real_cwd.get_cwd(),
                          os.path.join(temp_dir, "foo123456"))

    def test_cwd_relative_completion(self):
        temp_dir = self.make_temp_dir()
        os.mkdir(os.path.join(temp_dir, "foo-dir"))
        sh = self.make_shell()
        sh.run_command("cd %s" % temp_dir, default_fds())
        self.assertEquals(sh.completer("echo ", ""), ["foo-dir/"])

    def test_cwd_relative_redirection(self):
        temp_dir = self.make_temp_dir()
        write_file(os.path.join(temp_dir, "input123"), "foo")
        sh = self.make_shell()
        sh.run_command("cd %s" % temp_dir, default_fds())
        write_stdout, read_stdout = make_fh_pair()
        sh.run_command("cat < input123", {1: write_stdout, 2: sys.stderr})
        self.assertEquals(read_stdout.read(), "foo")

    def test_cwd_relative_globbing(self):
        temp_dir = self.make_temp_dir()
        write_file(os.path.join(temp_dir, "input123"), "")
        sh = self.make_shell()
        sh.run_command("cd %s" % temp_dir, default_fds())
        write_stdout, read_stdout = make_fh_pair()
        sh.run_command("echo in*", {1: write_stdout, 2: sys.stderr})
        self.assertEquals(read_stdout.read(), "input123\n")


class JobControlTests(unittest.TestCase):

    def setUp(self):
        messages = []
        class Output(object):
            def write(self, message):
                messages.append(message)

        def assert_messages(expected):
            self.job_controller.print_messages()
            self.assertEquals(pop_all(messages), expected)

        self._shell = shell.Shell({"job_output": Output()})
        self.dispatcher = self._shell.wait_dispatcher
        self.job_controller = self._shell.job_controller
        self.assert_messages = assert_messages

    def run_job_command(self, command, fds):
        self._shell.run_command(command, fds)

    def test_exit_status(self):
        pid = os.fork()
        if pid == 0:
            os._exit(123)
        got = []
        self.dispatcher.add_handler(pid, got.append)
        self.dispatcher.once(may_block=True)
        self.assertEquals(len(got), 1)
        self.assertTrue(os.WIFEXITED(got[0]))
        self.assertEquals(os.WEXITSTATUS(got[0]), 123)

    def test_stop_status(self):
        pid = os.fork()
        if pid == 0:
            try:
                os.kill(os.getpid(), signal.SIGSTOP)
            finally:
                os._exit(123)
        got = []
        self.dispatcher.add_handler(pid, got.append)
        self.dispatcher.once(may_block=True)
        os.kill(pid, signal.SIGKILL)
        self.assertEquals(len(got), 1)
        self.assertTrue(os.WIFSTOPPED(got[0]))
        self.assertEquals(os.WSTOPSIG(got[0]), signal.SIGSTOP)

    def test_foreground(self):
        # Foregrounding is necessary to set signals otherwise we get
        # wedged by SIGTTOU.  TODO: tests should not be vulnerable to
        # this and should not assume they are run with a tty.
        self.job_controller.shell_to_foreground()
        self.run_job_command(
            "true",
            std_fds(stdin=sys.stdin, stdout=sys.stdout, stderr=sys.stderr))
        self.job_controller.shell_to_foreground()
        self.assertEquals(self.job_controller.jobs.keys(), [])
        self.assert_messages([])

    def test_foreground_job_is_stopped(self):
        self.job_controller.shell_to_foreground()
        command = "sh -c 'kill -STOP $$'"
        self.run_job_command(
            command,
            std_fds(stdin=sys.stdin, stdout=sys.stdout, stderr=sys.stderr))
        self.job_controller.shell_to_foreground()
        jobs = self.job_controller.jobs
        self.assertEquals(jobs.keys(), [1])
        job = jobs[1]
        try:
            self.assert_messages(["[1]+ Stopped  %s\n" % command])
        finally:
            job.resume()
        self.dispatcher.once(may_block=True)
        self.assertEquals(job.state, "finished")
        self.assert_messages(["[1]+ Done  %s\n" % command])
        self.assertEquals(jobs.keys(), [])

    def test_backgrounding(self):
        jobs = self.job_controller.jobs
        command = "sh -c 'while true; do sleep 1s; done' &"
        self.run_job_command(
            command,
            std_fds(stdin=sys.stdin, stdout=sys.stdout, stderr=sys.stderr))
        self.assertEquals(jobs.keys(), [1])
        job = jobs[1]
        try:
            self.assertEquals(job.state, "running")
            self.assert_messages(["[1] %i\n" % job.pgid])
            job.send_signal(signal.SIGSTOP)
            # Signal delivery is apparently not immediate so we need to block.
            self.dispatcher.once(may_block=True)
            self.assertEquals(job.state, "stopped")
            self.assert_messages(["[1]+ Stopped  %s\n" % command])

            # Check that the wait status handlers work a second time.
            job.resume()
            self.assertEquals(job.state, "running")
            self.assert_messages([])
            job.send_signal(signal.SIGSTOP)
            self.dispatcher.once(may_block=True)
            self.assertEquals(job.state, "stopped")
            self.assert_messages(["[1]+ Stopped  %s\n" % command])
        finally:
            job.send_signal(signal.SIGKILL)
        self.dispatcher.once(may_block=True)
        self.assertEquals(job.state, "finished")
        self.assert_messages(["[1]+ Done  %s\n" % command])
        self.assertEquals(jobs.keys(), [])

    def test_listing_jobs(self):
        self.run_job_command(
            "true &",
            std_fds(stdin=sys.stdin, stdout=sys.stdout, stderr=sys.stderr))
        self.dispatcher.once(may_block=True)
        write_fh, read_fh = make_fh_pair()
        self.run_job_command(
            "jobs",
            std_fds(stdin=sys.stdin, stdout=write_fh, stderr=sys.stderr))
        self.assertEquals(read_fh.read(), "[1] Done  true &\n")

    def test_bg(self):
        self.job_controller.shell_to_foreground()
        write_fd, read_fd = make_fh_pair()
        command = "sh -c 'echo start; kill -STOP $$; echo done'"
        self.run_job_command(
            command,
            std_fds(stdin=sys.stdin, stdout=write_fd, stderr=sys.stderr))
        self.assert_messages(["[1]+ Stopped  %s\n" % command])
        self.assertEquals(read_fd.read(), "start\n")

        self.run_job_command(
            "bg", 
            std_fds(stdin=sys.stdin, stdout=sys.stdout, stderr=sys.stderr))
        self.dispatcher.once(may_block=True)
        self.assertEquals(read_fd.read(), "done\n")
        self.assert_messages(["[1]+ Done  %s\n" % command])

    def test_fg(self):
        self.job_controller.shell_to_foreground()
        write_fd, read_fd = make_fh_pair()
        self.run_job_command(
            "sh -c 'echo start; kill -STOP $$; echo done'",
            std_fds(stdin=sys.stdin, stdout=write_fd, stderr=sys.stderr))
        self.assertEquals(read_fd.read(), "start\n")

        self.run_job_command(
            "fg", 
            std_fds(stdin=sys.stdin, stdout=sys.stdout, stderr=sys.stderr))
        try:
            os.waitpid(-1, os.WNOHANG | os.WUNTRACED)
        except OSError, exn:
            self.assertEquals(exn.errno, errno.ECHILD)
        else:
            self.fail("Expected ECHILD")
        self.assertEquals(read_fd.read(), "done\n")
        self.assert_messages([])


class HistoryTest(TestCase):

    def test_creating_database(self):
        self.patch_env_var("HOME", self.make_temp_dir())
        sh = make_shell({"history": shell.History()})
        sh.run_command("true", {})
        # Test instantiating the database object a second time.
        history = shell.History()
        cursor = history._sqldb.execute("SELECT command FROM history")
        self.assertEquals(list(cursor), [("true",)])


if __name__ == "__main__":
    unittest.main()
