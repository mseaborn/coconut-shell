
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

import subprocess
import unittest

import terminal


class TerminalSizeTest(unittest.TestCase):

    def test_setting_terminal_size(self):
        master_fd, slave_fd = terminal.openpty()
        terminal.set_terminal_size(slave_fd, 123, 456)
        proc = subprocess.Popen(["stty", "size"], stdin=slave_fd,
                                stdout=subprocess.PIPE)
        stdout = proc.communicate()[0]
        self.assertEquals(stdout, "456 123\n")


if __name__ == "__main__":
    unittest.main()
