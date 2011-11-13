
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
import os.path
import stat
import subprocess
import unittest

import lscolors
import tempdir_test


class ParseLsColorsTestCase(unittest.TestCase):

    def test_parse_ls_colors(self):
        self.assertRaises(AssertionError, lscolors.parse_ls_colors, "")
        self.assertRaises(AssertionError, lscolors.parse_ls_colors, "::")
        self.assertEquals(lscolors.parse_ls_colors("*.awk=38;5;148;1"), 
                          {".awk": "38;5;148;1"})
        self.assertEquals(lscolors.parse_ls_colors("*.tar.gz=38;5;148;1"), 
                          {".tar.gz": "38;5;148;1"})
        self.assertEquals(
            lscolors.parse_ls_colors("*.awk=38;5;148;1:di=38;5;30"), 
            {".awk": "38;5;148;1", "di": "38;5;30"})


class ColorKeyForFileTestCase(tempdir_test.TempDirTestCase):

    COLOR_CODES = {lscolors.OTHER_WRITABLE_KEY: "other writable", 
                   lscolors.EXECUTABLE_KEY: "executable", 
                   lscolors.ORPHAN_KEY: "orphan", 
                   lscolors.SETGUID_KEY: "setguid", 
                   lscolors.SETUID_KEY: "setuid", 
                   lscolors.STICKY_KEY: "sticky", 
                   lscolors.STICKY_OTHER_WRITABLE_KEY: "sticky other writable",
                   lscolors.MULTI_HARDLINK_KEY: "multi hardlink", 
                   lscolors.CHARACTER_DEVICE_KEY: "character device", 
                   lscolors.BLOCK_DEVICE_KEY: "block device"}

    def test_color_key_for_path_without_extension(self):
        temp_dir = self.make_temp_dir()
        executable_path = os.path.join(temp_dir, "foo")
        open(executable_path, "w").close()
        self.assertEquals(
            lscolors.color_key_for_path(executable_path, self.COLOR_CODES), 
            lscolors.FILE_KEY)

    def test_color_key_for_path_with_extension(self):
        temp_dir = self.make_temp_dir()
        awk_path = os.path.join(temp_dir, "test.awk")
        open(awk_path, "w").close()
        self.assertEquals(
            lscolors.color_key_for_path(awk_path, self.COLOR_CODES), 
            lscolors.FILE_KEY)

    def test_color_key_for_path_with_double_extension(self):
        temp_dir = self.make_temp_dir()
        tar_gz_path = os.path.join(temp_dir, "test.tar.gz")
        open(tar_gz_path, "w").close()
        self.assertEquals(
            lscolors.color_key_for_path(tar_gz_path, self.COLOR_CODES), 
            lscolors.FILE_KEY)

    def test_color_code_for_directory(self):
        temp_dir = self.make_temp_dir()
        self.assertEquals(
            lscolors.color_key_for_path(temp_dir, self.COLOR_CODES), 
            lscolors.DIRECTORY_KEY)

    def test_color_code_for_directory_thats_other_writable(self):
        temp_dir = self.make_temp_dir()
        mode = os.stat(temp_dir).st_mode
        os.chmod(temp_dir, mode | stat.S_IWOTH)
        self.assertEquals(
            lscolors.color_key_for_path(temp_dir, self.COLOR_CODES), 
            lscolors.OTHER_WRITABLE_KEY)

    def test_color_code_for_executable(self):
        temp_dir = self.make_temp_dir()
        executable_path = os.path.join(temp_dir, "a")
        open(executable_path, "w").close()
        os.chmod(executable_path, stat.S_IEXEC)
        self.assertEquals(
            lscolors.color_key_for_path(executable_path, self.COLOR_CODES), 
            lscolors.EXECUTABLE_KEY)

    def test_color_code_for_executable_with_extension(self):
        temp_dir = self.make_temp_dir()
        executable_path = os.path.join(temp_dir, "a.awk")
        open(executable_path, "w").close()
        os.chmod(executable_path, stat.S_IEXEC)
        self.assertEquals(
            lscolors.color_key_for_path(executable_path, self.COLOR_CODES), 
            lscolors.EXECUTABLE_KEY)

    def test_color_code_for_setguid(self):
        temp_dir = self.make_temp_dir()
        setguid_path = os.path.join(temp_dir, "a")
        open(setguid_path, "w").close()
        os.chmod(setguid_path, stat.S_ISGID)
        self.assertEquals(
            lscolors.color_key_for_path(setguid_path, self.COLOR_CODES), 
            lscolors.SETGUID_KEY)

    def test_color_code_for_setuid(self):
        temp_dir = self.make_temp_dir()
        setuid_path = os.path.join(temp_dir, "a")
        open(setuid_path, "w").close()
        os.chmod(setuid_path, stat.S_ISUID)
        self.assertEquals(
            lscolors.color_key_for_path(setuid_path, self.COLOR_CODES), 
            lscolors.SETUID_KEY)

    def test_color_code_for_broken_symlink(self):
        temp_dir = self.make_temp_dir()
        symlink_path = os.path.join(temp_dir, "b")
        os.symlink(os.path.join(temp_dir, "a"), symlink_path)
        self.assertEquals(
            lscolors.color_key_for_path(symlink_path, self.COLOR_CODES), 
            lscolors.ORPHAN_KEY)

    def test_color_code_for_good_symlink(self):
        temp_dir = self.make_temp_dir()
        symlink_path = os.path.join(temp_dir, "b")
        awk_path = os.path.join(temp_dir, "test.awk")
        open(awk_path, "w").close()
        os.symlink(awk_path, symlink_path)
        self.assertEquals(
            lscolors.color_key_for_path(symlink_path, self.COLOR_CODES), 
            lscolors.FILE_KEY)

    def test_color_code_for_pipe(self):
        temp_dir = self.make_temp_dir()
        pipe_path = os.path.join(temp_dir, "a")
        os.mkfifo(pipe_path)
        self.assertEquals(
            lscolors.color_key_for_path(pipe_path, self.COLOR_CODES), 
            lscolors.PIPE_KEY)

    def test_color_code_for_character_device(self):
        character_device_path = "/dev/tty"
        self.assertEquals(
            lscolors.color_key_for_path(character_device_path, 
                                        self.COLOR_CODES), 
            lscolors.CHARACTER_DEVICE_KEY)

    def test_color_code_for_block_device(self):
        block_device_path = "/dev/loop0"
        self.assertEquals(
            lscolors.color_key_for_path(block_device_path, self.COLOR_CODES), 
            lscolors.BLOCK_DEVICE_KEY)

    def test_color_code_for_sticky_directory(self):
        temp_dir = self.make_temp_dir()
        mode = os.stat(temp_dir).st_mode
        os.chmod(temp_dir, mode | stat.S_ISVTX)
        self.assertEquals(
            lscolors.color_key_for_path(temp_dir, self.COLOR_CODES), 
            lscolors.STICKY_KEY)

    def test_color_code_for_sticky_and_other_writable(self):
        temp_dir = self.make_temp_dir()
        mode = os.stat(temp_dir).st_mode
        os.chmod(temp_dir, mode | stat.S_ISVTX | stat.S_IWOTH)
        self.assertEquals(
            lscolors.color_key_for_path(temp_dir, self.COLOR_CODES), 
            lscolors.STICKY_OTHER_WRITABLE_KEY)

    def test_color_code_for_socket(self):
        socket_path = "/dev/log"
        self.assertEquals(
            lscolors.color_key_for_path(socket_path, self.COLOR_CODES), 
            lscolors.SOCKET_KEY)

    def test_color_code_for_missing_file(self):
        temp_dir = self.make_temp_dir()
        missing_path = os.path.join(temp_dir, "a")
        self.assertEquals(
            lscolors.color_key_for_path(missing_path, self.COLOR_CODES), 
            lscolors.MISSING_KEY)

    def test_color_code_for_multi_hardlink(self):
        temp_dir = self.make_temp_dir()
        a_path = os.path.join(temp_dir, "a")
        open(a_path, "w").close()
        b_path = os.path.join(temp_dir, "b")
        os.link(a_path, b_path)
        self.assertEquals(
            lscolors.color_key_for_path(a_path, self.COLOR_CODES), 
            lscolors.MULTI_HARDLINK_KEY)
        

class ColorCodeForFileTestCase(tempdir_test.TempDirTestCase):

    AWK_COLOR = "awk color"
    TAR_GZ_COLOR = "tar gz color"
    COLOR_CODES = {
        ".awk": AWK_COLOR, ".tar.gz": TAR_GZ_COLOR}

    def test_color_code_for_path_without_extension(self):
        temp_dir = self.make_temp_dir()
        file_path = os.path.join(temp_dir, "foo")
        open(file_path, "w").close()
        self.assertEquals(
            lscolors.color_code_for_path(file_path, {"fi": "file color"}), 
            "file color")

    def test_color_code_for_path_with_extension(self):
        temp_dir = self.make_temp_dir()
        awk_path = os.path.join(temp_dir, "test.awk")
        open(awk_path, "w").close()
        self.assertEquals(
            lscolors.color_code_for_path(awk_path, self.COLOR_CODES), 
            self.AWK_COLOR)

    def test_color_code_for_path_with_double_extension(self):
        temp_dir = self.make_temp_dir()
        tar_gz_path = os.path.join(temp_dir, "test.tar.gz")
        open(tar_gz_path, "w").close()
        self.assertEquals(
            lscolors.color_code_for_path(tar_gz_path, self.COLOR_CODES), 
            self.TAR_GZ_COLOR)


class StringInColorTestCase(unittest.TestCase):

    def test_string_in_color(self):
        self.assertEquals(lscolors.string_in_color("foo", "38;5;148;1"), 
                          "\x1b[38;5;148;1mfoo\x1b[0m")


class ColoredStringTestCase(unittest.TestCase):

    def test_colored_string(self):
        a = lscolors.ColoredString("foobar")
        self.assertEquals(type(a), lscolors.ColoredString)
        self.assertEquals(a.color_code, None)
        self.assertEquals(a, "foobar")
        self.assertEquals(str(a), "foobar")
        self.assertEquals(repr(a), "<ColoredString 'foobar' None>")
        self.assert_(a.startswith("foo"))
        slice_ = a[2:4]
        self.assertEquals(slice_, "ob")
        self.assertEquals(type(slice_), lscolors.ColoredString)
        a.set_color("12")
        self.assertEquals(a.color_code, "12")
        self.assertEquals(a, "foobar")
        self.assertEquals(str(a), "\x1b[12mfoobar\x1b[0m")
        self.assertEquals(repr(a), "<ColoredString 'foobar' 12>")
        self.assertEquals(a[2:4].color_code, "12")


def parse_ls_line(line):
    parts = line.split("\x1b[")
    if len(parts) == 1:
        return (None, line)
    for part in parts:
        end_color_code = part.find("m")
        if end_color_code < (len(part) - 1):
            return tuple(part.split("m", 1))


class ParseLsLineTestCase(unittest.TestCase):

    def test_parse_ls_line(self):
        self.assertEquals(parse_ls_line(
                "\x1b[0m\x1b[38;5;254m\x1b[m\x1b[38;5;30mhello\x1b[0m\n"), 
                          ("38;5;30", "hello"))


def test_against_ls(root_path, environment):
    process = subprocess.Popen(
        ["ls", "--color=always", "-R", root_path], 
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=environment)
    stdout, stderr = process.communicate()
    color_codes = lscolors.get_color_codes(environment)
    for line in stdout.splitlines():
        line = line.strip()
        if line == "":
            continue
        if line.endswith(":"):
            current_directory = line[:-1]
            continue
        ls_color_code, filename = parse_ls_line(line)
        path = os.path.join(current_directory, filename)
        if os.path.exists(path): # Some paths are already gone. e.g. in /proc
            color_code = lscolors.color_code_for_path(path, color_codes)
            if color_code != ls_color_code:
                print "%s %r %r" % (path, color_code, ls_color_code)


RICH_COLOR_CODES = (
    "bd=38;5;68:ca=38;5;17:cd=38;5;113;1:di=38;5;30:do=38;5;127:"
    "ex=38;5;166;1:pi=38;5;126:fi=38;5;253:ln=target:mh=38;5;220;1:"
    "no=38;5;254:or=48;5;196;38;5;232;1:ow=38;5;33;1:sg=38;5;137;1:"
    "su=38;5;137:so=38;5;197:st=48;5;235;38;5;118;1:tw=48;5;235;38;5;139;1:"
    "*.BAT=38;5;108:*.PL=38;5;160:*.asm=38;5;240;1:*.awk=38;5;148;1:"
    "*.bash=38;5;173:*.bat=38;5;108:*.c=38;5;110:*.cfg=1:*.coffee=38;5;94;1:"
    "*.conf=1:*.cpp=38;5;24;1:*.cs=38;5;74;1:*.css=38;5;91:*.csv=38;5;78:"
    "*.diff=48;5;197;38;5;232:*.enc=38;5;192;3")


if __name__ == "__main__":
    unittest.main()
    # root_path = "/"
    # test_against_ls(root_path, {"LS_COLORS": RICH_COLOR_CODES})
    # test_against_ls(root_path, {})  # Test using default colors
