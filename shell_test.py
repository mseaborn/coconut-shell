
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


def command_output(command):
    write_fh, read_fh = make_fh_pair()
    shell.run_command(command, stdin=open(os.devnull, "r"), stdout=write_fh)
    return read_fh.read()


class ShellTests(tempdir_test.TempDirTestCase):

    def test_simple(self):
        data = command_output('echo foo "bar baz"')
        self.assertEquals(data, "foo bar baz\n")

    def test_quoting(self):
        data = command_output("echo foo  'bar  baz' ''")
        self.assertEquals(data, "foo bar  baz \n")

    def test_punctuation(self):
        data = command_output('echo . +')
        self.assertEquals(data, ". +\n")

    def test_pipeline(self):
        data = command_output(
            "echo foo | sh -c 'echo open && cat && echo close'")
        self.assertEquals(data, "open\nfoo\nclose\n")

    def test_breaking_pipe(self):
        # "yes" should exit because its pipe is broken.
        data = command_output("yes | echo done")
        self.assertEquals(data, "done\n")

    def test_syntax_error(self):
        self.assertRaises(parse.ParseException,
                          lambda: command_output('echo \000'))

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
