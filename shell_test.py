
import os
import tempfile
import unittest

import shell


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


class ShellTests(unittest.TestCase):

    def test(self):
        write_fh, read_fh = make_fh_pair()
        shell.run_command('echo foo "bar baz"', stdout=write_fh)
        data = read_fh.read()
        self.assertEquals(data, "foo bar baz\n")


if __name__ == "__main__":
    unittest.main()
