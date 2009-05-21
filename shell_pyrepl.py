
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

import gobject

import pyrepl.completing_reader
import pyrepl.historical_reader
import pyrepl.unix_console


class Reader(pyrepl.historical_reader.HistoricalReader,
             pyrepl.completing_reader.CompletingReader):

    def __init__(self, get_prompt, completer, *args):
        self._get_prompt = get_prompt
        self._completer = completer
        super(Reader, self).__init__(*args)

    def get_prompt(self, lineno, cursor_on_line):
        return self._get_prompt()

    def get_stem(self):
        buffer = "".join(self.buffer)
        index = buffer.rfind(" ", 0, self.pos)
        if index == -1:
            self._completion_context = ""
            return buffer[:self.pos]
        else:
            self._completion_context = buffer[:index+1]
            return buffer[index+1:self.pos]

    def get_completions(self, stem):
        return list(self._completer(self._completion_context, stem))

    def clear_error(self):
        self.msg = ""
        self.dirty = True

    def readline(self, callback):
        def on_avail(*args):
            try:
                self.handle1()
            except EOFError:
                self.restore()
                callback(None)
                return False
            if self.finished:
                self.restore()
                callback(self.get_buffer())
                return False
            return True

        self.prepare()
        gobject.io_add_watch(1, gobject.IO_IN, on_avail)
        self.refresh()


def make_reader(get_prompt, completer):
    return Reader(get_prompt, completer, pyrepl.unix_console.UnixConsole())
