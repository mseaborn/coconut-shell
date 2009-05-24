
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

import os
import sys
import unittest

import gobject

import setsid_helper
import terminal


class HelperTest(unittest.TestCase):

    def test_setsid_helper(self):
        got = []
        def callback(pid, status):
            got.append((pid, status))

        spec1 = {"args": ["sh", "-c", "exit 42"],
                "fds": {0: sys.stdin, 1: sys.stdout, 2: sys.stderr}}
        spec2 = {"args": ["sh", "-c", "exit 24"],
                 "fds": {0: sys.stdin, 1: sys.stdout, 2: sys.stderr}}
        master_fd, slave_fd = terminal.openpty()
        helper_pid, pids = setsid_helper.run([spec1, spec2], slave_fd, callback)
        self.assertEquals(len(pids), 2)
        gobject.main_context_default().iteration(True)
        gobject.main_context_default().iteration(True)
        gobject.main_context_default().iteration(True)
        statuses = dict(got)
        self.assertEquals(set(statuses.keys()), set(pids))
        assert os.WIFEXITED(statuses[pids[0]])
        assert os.WIFEXITED(statuses[pids[1]])
        self.assertEquals(os.WEXITSTATUS(statuses[pids[0]]), 42)
        self.assertEquals(os.WEXITSTATUS(statuses[pids[1]]), 24)

        # Helper process should exit OK.
        pid2, status = os.waitpid(helper_pid, 0)
        assert os.WIFEXITED(status)
        self.assertEquals(os.WEXITSTATUS(status), 0)


if __name__ == "__main__":
    unittest.main()
