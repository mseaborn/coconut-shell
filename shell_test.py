
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

import os
import signal
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
        write_fh = os.fdopen(fd, "w")
        read_fh = open(filename, "r")
    finally:
        os.unlink(filename)
    return write_fh, read_fh


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


class ShellTests(tempdir_test.TempDirTestCase):

    def patch_env_var(self, key, value):
        old_value = os.environ.get(key)
        set_env_var(key, value)
        self.on_teardown(lambda: set_env_var(key, old_value))

    def command_output(self, command):
        write_stdout, read_stdout = make_fh_pair()
        write_stderr, read_stderr = make_fh_pair()
        job_controller = shell.NullJobController()
        shell.run_command(job_controller, command, stdin=open(os.devnull, "r"),
                          stdout=write_stdout, stderr=write_stderr)
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

    def test_completion(self):
        temp_dir = self.make_temp_dir()
        os.mkdir(os.path.join(temp_dir, "a-dir"))
        os.mkdir(os.path.join(temp_dir, "b-dir"))
        write_file(os.path.join(temp_dir, "a-file"), "")
        os.chdir(temp_dir)
        self.assertEquals(list(shell.readline_complete("a-")),
                          ["a-dir/", "a-file"])

    def test_completion_with_tilde_expansion(self):
        home_dir = self.make_temp_dir()
        self.patch_env_var("HOME", home_dir)
        os.mkdir(os.path.join(home_dir, "a-dir"))
        os.mkdir(os.path.join(home_dir, "b-dir"))
        # Recent versions of Bash expand out ~ when doing completion,
        # but we leave the ~ in place, which I prefer.
        self.assertEquals(list(shell.readline_complete("~/a-")),
                          ["~/a-dir/"])


class JobControlTests(unittest.TestCase):

    def setUp(self):
        messages = []
        class Output(object):
            def write(self, message):
                messages.append(message)

        def assert_messages(expected):
            self.job_controller.print_messages()
            self.assertEquals(pop_all(messages), expected)

        self.dispatcher = jobcontrol.WaitDispatcher()
        self.job_controller = jobcontrol.JobController(
            self.dispatcher, Output())
        self.assert_messages = assert_messages

    def test_foreground(self):
        # Foregrounding is necessary to set signals otherwise we get
        # wedged by SIGTTOU.  TODO: tests should not be vulnerable to
        # this and should not assume they are run with a tty.
        self.job_controller.shell_to_foreground()
        shell.run_command(
            self.job_controller, "true",
            stdin=sys.stdin, stdout=sys.stdout, stderr=sys.stderr)
        self.job_controller.shell_to_foreground()
        self.assertEquals(self.job_controller.jobs.keys(), [])
        self.assert_messages([])

    def test_foreground_job_is_stopped(self):
        self.job_controller.shell_to_foreground()
        shell.run_command(
            self.job_controller, "sh -c 'kill -STOP $$'",
            stdin=sys.stdin, stdout=sys.stdout, stderr=sys.stderr)
        self.job_controller.shell_to_foreground()
        jobs = self.job_controller.jobs
        self.assertEquals(jobs.keys(), [1])
        job = jobs[1]
        try:
            self.assert_messages(["[1]+ Stopped\n"])
        finally:
            job.resume()
        self.dispatcher.once(may_block=True)
        self.assertEquals(job.state, "finished")
        self.assert_messages(["[1]+ Done\n"])
        self.assertEquals(jobs.keys(), [])

    def test_backgrounding(self):
        jobs = self.job_controller.jobs
        shell.run_command(
            self.job_controller,
            "sh -c 'while true; do sleep 1s; done' &",
            stdin=sys.stdin, stdout=sys.stdout, stderr=sys.stderr)
        self.assertEquals(jobs.keys(), [1])
        job = jobs[1]
        try:
            self.assertEquals(job.state, "running")
            self.assert_messages(["[1] %i\n" % job.pgid])
            job.send_signal(signal.SIGSTOP)
            # Signal delivery is apparently not immediate so we need to block.
            self.dispatcher.once(may_block=True)
            self.assertEquals(job.state, "stopped")
            self.assert_messages(["[1]+ Stopped\n"])

            # Check that the wait status handlers work a second time.
            job.resume()
            self.assertEquals(job.state, "running")
            self.assert_messages([])
            job.send_signal(signal.SIGSTOP)
            self.dispatcher.once(may_block=True)
            self.assertEquals(job.state, "stopped")
            self.assert_messages(["[1]+ Stopped\n"])
        finally:
            job.send_signal(signal.SIGKILL)
        self.dispatcher.once(may_block=True)
        self.assertEquals(job.state, "finished")
        self.assert_messages(["[1]+ Done\n"])
        self.assertEquals(jobs.keys(), [])


if __name__ == "__main__":
    unittest.main()
