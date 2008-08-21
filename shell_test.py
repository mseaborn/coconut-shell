
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

    def test_simple(self):
        write_fh, read_fh = make_fh_pair()
        shell.run_command('echo foo "bar baz"', stdout=write_fh)
        data = read_fh.read()
        self.assertEquals(data, "foo bar baz\n")

    def test_punctuation(self):
        write_fh, read_fh = make_fh_pair()
        shell.run_command('echo . +', stdout=write_fh)
        data = read_fh.read()
        self.assertEquals(data, ". +\n")

    def test_syntax_error(self):
        write_fh, read_fh = make_fh_pair()
        self.assertRaises(
            parse.ParseException,
            lambda: shell.run_command('echo \000', stdout=write_fh))

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
