
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
