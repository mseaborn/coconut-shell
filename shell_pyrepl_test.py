
# Copyright (C) 2011 Andrew Hamilton
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
import unittest

import shell
import shell_pyrepl
import tempdir_test


class MockConsole():
    width = 80
    encoding = "UTF8"

    def restore(self):
        pass

    def prepare(self):
        pass

    def refresh(self, foo, bah):
        pass


class ReaderTestCase(tempdir_test.TempDirTestCase):

    def test_tab_completion(self):
        mock_console = MockConsole()
        shell_ = shell.Shell({})
        reader = shell_pyrepl.Reader(
            shell_.get_prompt, shell_.completer, shell_.cwd, mock_console)
        def test_case(filenames, stem, completed_filename, 
                      start_position=None, command="ls "):
            if start_position is None:
                start_position = len(stem)
            temp_dir = self.make_temp_dir()
            for filename in filenames:
                if filename.endswith("/"):
                    os.mkdir(os.path.join(temp_dir, filename[:-1]))
                else:
                    open(os.path.join(temp_dir, filename), "w").close()
            os.chdir(temp_dir)
            reader.prepare()
            reader.insert(command + stem)
            reader.pos = len(command) + start_position
            reader.do_cmd(["complete", None])
            expected = command + completed_filename
            self.assertEquals(reader.get_buffer(), expected)
            self.assertEquals(reader.pos, 
                              len(expected) - len(stem) + start_position)
        test_case(["foo"], "f", "foo")
        test_case(["foo bar"], "f", '"foo bar"')
        test_case(["foo bar", "foo baz"], "f", '"foo ba')
        test_case(["foo bar"], "fo baz", '"foo bar" baz', 2)
        test_case(["ffffff"], "ffff", "ffffff", command="")
        for quote in ['"', "'"]:
            test_case(["foo"], quote + "f", quote + "foo" + quote)
            test_case(["foo bar"], quote + "f", quote + "foo bar" + quote)
            test_case(["foo bar"], quote + "foo ", quote + "foo bar" + quote)
            test_case(["foo bar"], "%sbaz%s foo" % (quote, quote), 
                      '%sbaz%s "foo bar"' % (quote, quote))
            test_case(["foo/"], quote + "f", quote + "foo/")
            test_case(["foo bar/"], quote + "f", quote + "foo bar/")
            test_case(["foo bar", "foo baz"], quote + 'foo b', 
                      quote + 'foo ba')


if __name__ == "__main__":
    unittest.main()
