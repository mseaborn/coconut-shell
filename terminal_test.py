
# Copyright (C) 2009 Mark Seaborn
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

import itertools
import os
import subprocess
import time
import unittest

import gobject

import tempdir_test
import terminal


class TerminalSizeTest(unittest.TestCase):

    def test_setting_terminal_size(self):
        master_fd, slave_fd = terminal.openpty()
        terminal.set_terminal_size(slave_fd, 123, 456)
        proc = subprocess.Popen(["stty", "size"], stdin=slave_fd,
                                stdout=subprocess.PIPE)
        stdout = proc.communicate()[0]
        self.assertEquals(stdout, "456 123\n")


def get_vte_text(vte_terminal):
    # VTE updates the terminal in the event loop after a
    # non-configurable timeout, so we have to work around that.
    time.sleep(0.05)
    gobject.main_context_default().iteration(False)
    return vte_terminal.get_text(lambda *args: True)


def make_template():
    return {"get_prompt": lambda: "$ "}


class TerminalTest(tempdir_test.TempDirTestCase):

    def test_gui_instantiation(self):
        terminal.make_terminal({})

    def test_not_using_enclosing_tty(self):
        saved_fds = [os.dup(fd) for fd in (0, 1, 2)]
        try:
            for fd in (0, 1, 2):
                os.close(fd)
            terminal.make_terminal({})
        finally:
            for orig_fd, saved_fd in enumerate(saved_fds):
                os.dup2(saved_fd, orig_fd)

    def test_not_using_tty_size_env_vars(self):
        if "LINES" in os.environ:
            del os.environ["LINES"]
        if "COLUMNS" in os.environ:
            del os.environ["COLUMNS"]
        terminal.make_terminal({})

    def test_not_using_term_env_var(self):
        # Note that os.environ.pop() does not work.
        if "TERM" in os.environ:
            del os.environ["TERM"]
        terminal.make_terminal({})

    def test_terminal_contents(self):
        vte = terminal.TerminalWidget(make_template()).get_terminal_widget()
        screen = "".join(get_vte_text(vte)).rstrip("\n")
        self.assertEquals(screen, "$ ")

    def test_command_output(self):
        term = terminal.TerminalWidget(make_template())
        term._current_reader("echo hello\n")
        while term._shell.job_controller._awaiting_job is not None:
            gobject.main_context_default().iteration(False)
        screen = "".join(get_vte_text(term.get_terminal_widget())).rstrip("\n")
        self.assertEquals(screen, "$ echo hello\nhello\n$ ")

    def test_clone(self):
        temp_dir = self.make_temp_dir()
        term1 = terminal.TerminalWidget(make_template())
        term1._shell.cwd.chdir(temp_dir)
        term2 = term1.clone()
        self.assertEquals(term2._shell.cwd.get_cwd(), temp_dir)
        self.assertEquals(term2._shell.environ["PWD"], temp_dir)
        assert term1._shell.environ is not term2._shell.environ

    def test_reading_pending_data(self):
        term = terminal.TerminalWidget(make_template())
        term._terminal.set_size(100, 100)
        data = "".join(itertools.islice((char for i in itertools.count()
                                         for char in str(i)), 3000))
        term._process_input("echo %s\n" % data)
        while term._shell.job_controller._awaiting_job is not None:
            gobject.main_context_default().iteration(False)
        screen = "".join(get_vte_text(term.get_terminal_widget())).rstrip("\n")
        self.assertEquals(screen, "$ " + data + "\n$ ")

    def test_term_variable(self):
        term = terminal.TerminalWidget({})
        self.assertEquals(term._shell.environ["TERM"], "xterm")


if __name__ == "__main__":
    unittest.main()
