
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
import tempfile
import unittest

import pyparsing as parse

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


class ShellTests(tempdir_test.TempDirTestCase):

    def command_output(self, command):
        write_stdout, read_stdout = make_fh_pair()
        write_stderr, read_stderr = make_fh_pair()
        shell.run_command(command, stdin=open(os.devnull, "r"),
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

    def test_breaking_pipe(self):
        # "yes" should exit because its pipe is broken.
        data = self.command_output("yes | echo done")
        self.assertEquals(data, "done\n")

    def test_syntax_error(self):
        self.assertRaises(parse.ParseException,
                          lambda: self.command_output('echo \000'))

    def test_completion(self):
        temp_dir = self.make_temp_dir()
        os.mkdir(os.path.join(temp_dir, "a-dir"))
        os.mkdir(os.path.join(temp_dir, "b-dir"))
        fh = open(os.path.join(temp_dir, "a-file"), "w")
        fh.close()
        os.chdir(temp_dir)
        self.assertEquals(list(shell.readline_complete("a-")),
                          ["a-dir/", "a-file"])


if __name__ == "__main__":
    unittest.main()
