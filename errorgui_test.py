
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

import StringIO
import sys
import unittest

import errorgui
import tempdir_test


class ErrorDialogTest(tempdir_test.TempDirTestCase):

    def monkey_patch(self, obj, attr, value):
        old_value = getattr(obj, attr)
        setattr(obj, attr, value)
        def restore():
            setattr(obj, attr, old_value)
        self.on_teardown(restore)

    def test_except_hook(self):
        stream = StringIO.StringIO()
        self.monkey_patch(errorgui, "show_all", lambda window: None)
        self.monkey_patch(sys, "stderr", stream)
        try:
            raise Exception()
        except:
            info = sys.exc_info()
            errorgui.except_hook(*info)
            assert stream.getvalue().startswith("Traceback ")


if __name__ == "__main__":
    unittest.main()
