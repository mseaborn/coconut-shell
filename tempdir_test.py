
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

import shutil
import tempfile
import unittest


class TempDirMaker(object):

    def __init__(self, name="temp"):
        self._name = name
        self._temp_dirs = []

    def make_temp_dir(self):
        temp_dir = tempfile.mkdtemp(prefix="%s-" % self._name)
        self._temp_dirs.append(temp_dir)
        return temp_dir

    def tidy_up(self):
        for temp_dir in self._temp_dirs:
            shutil.rmtree(temp_dir)
        self._temp_dirs[:] = []


class TempDirTestCase(unittest.TestCase):

    def setUp(self):
        super(TempDirTestCase, self).setUp()
        self._temp_maker = TempDirMaker("tmp-%s" % self.__class__.__name__)

    def tearDown(self):
        super(TempDirTestCase, self).tearDown()
        self._temp_maker.tidy_up()

    def make_temp_dir(self):
        return self._temp_maker.make_temp_dir()
