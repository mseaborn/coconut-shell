
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

import pyrepl.commands
import pyrepl.completing_reader
import pyrepl.historical_reader
import pyrepl.unix_console


def complete_line(reader, stem, completion, quote_type, 
                  has_closing_quote):
    buffer_ = reader.get_buffer()
    start = buffer_[:reader.pos - len(stem)]
    end = buffer_[reader.pos:]
    if quote_type is None:
        quote_type = '"' if " " in completion else ""
    else:
        assert start.endswith(quote_type), start
        start = start[:-1]
    parts = [start, quote_type, completion]
    if has_closing_quote and not completion.endswith("/"):
        parts.extend(quote_type)
    parts.extend(end)
    line = "".join(parts)
    reader.set_buffer(line)
    reader.pos = len(line) - len(end)


class complete(pyrepl.completing_reader.complete):

    def do(self):
        r = self.reader
        stem = r.get_stem()
        if stem.startswith("'") or stem.startswith('"'):
            quote_type = stem[0]
            stem = stem[1:]
        else:
            quote_type = None
        r.cmpltn_menu_choices = completions = r.get_completions(stem)
        if len(completions) == 0:
            r.error("no matches")
        elif len(completions) == 1:
            if len(completions[0]) == len(stem) and \
                   r.last_command_is(self.__class__):
                r.msg = "[ sole completion ]"
                r.dirty = 1
            complete_line(r, stem, completions[0], quote_type, True)
        else:
            p = pyrepl.completing_reader.prefix(completions, len(stem))
            if p <> '':
                complete_line(r, stem, stem + p, quote_type, False)
            if r.last_command_is(self.__class__):
                if not r.cmpltn_menu_vis:
                    r.cmpltn_menu_vis = 1
                r.cmpltn_menu, r.cmpltn_menu_end = \
                    pyrepl.completing_reader.build_menu(
                    r.console, completions, r.cmpltn_menu_end)
                r.dirty = 1
            elif stem + p in completions:
                r.msg = "[ complete but not unique ]"
                r.dirty = 1
            else:
                r.msg = "[ not unique ]"
                r.dirty = 1


class Reader(pyrepl.historical_reader.HistoricalReader,
             pyrepl.completing_reader.CompletingReader):

    def __init__(self, get_prompt, completer, *args):
        self._get_prompt = get_prompt
        self._completer = completer
        super(Reader, self).__init__(*args)
        self.wrap_marker = ""
        self.commands["complete"] = complete
        # Override these to be no-ops.  Don't want to send self signals.
        self.commands["suspend"] = pyrepl.commands.Command
        self.commands["interrupt"] = pyrepl.commands.Command

    def get_prompt(self, lineno, cursor_on_line):
        if (cursor_on_line and self.isearch_direction <> 
            pyrepl.historical_reader.ISEARCH_DIRECTION_NONE):
            if (self.isearch_direction == 
                pyrepl.historical_reader.ISEARCH_DIRECTION_FORWARDS):
                direction = "forward"
            else:
                direction = "reverse"
            return "(%s-i-search `%s'): " % (direction, self.isearch_term)
        else:
            return self._get_prompt()

    def get_stem(self):
        buffer = "".join(self.buffer)
        if len([character for character in buffer 
                if character == '"']) % 2 == 1:  # Odd number of quotes
            index = buffer.rfind('"', 0, self.pos) - 1
        elif len([character for character in buffer 
                  if character == "'"]) % 2 == 1:
            index = buffer.rfind("'", 0, self.pos) - 1
        else:
            index = buffer.rfind(" ", 0, self.pos)
        if index == -1:
            self._completion_context = ""
            return buffer[:self.pos]
        else:
            quote_index = buffer.rfind(" ", 0, self.pos)
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

    def set_buffer(self, line):
        self.buffer = [character for character in line]
        self.dirty = 1


def make_reader(get_prompt, completer):
    return Reader(get_prompt, completer, pyrepl.unix_console.UnixConsole())
