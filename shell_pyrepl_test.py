
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
            shell_.get_prompt, shell_.completer, mock_console)
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
