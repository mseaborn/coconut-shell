
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

# Integrated terminal GUI and shell.

import os
import traceback

import gobject
import gtk
import vte

import pyrepl.unix_console

import shell
import shell_pyrepl


def openpty():
    master_fd, slave_fd = os.openpty()
    return os.fdopen(master_fd, "w"), os.fdopen(slave_fd, "w")


# Monkey patch pyrepl.unix_console.
# Using TCSADRAIN blocks, causing a deadlock.
import termios
termios.TCSADRAIN = termios.TCSANOW
pyrepl.unix_console.tcsetattr = lambda *args: None


class VTEConsole(pyrepl.unix_console.UnixConsole):

    def __init__(self, terminal):
        self._terminal = terminal
        pyrepl.unix_console.UnixConsole.__init__(self)

    # TODO: Don't use __ attributes in UnixConsole
    def flushoutput(self):
        for text, iscode in self._UnixConsole__buffer:
            self._terminal.feed(text.encode(self.encoding))
        del self._UnixConsole__buffer[:]


def forward_output_to_terminal(master_fd, terminal):
    def on_avail(*args):
        try:
            data = os.read(master_fd.fileno(), 1024)
        except OSError:
            return False
        else:
            terminal.feed(data)
            return len(data) > 0
    gobject.io_add_watch(
        master_fd.fileno(), gobject.IO_IN | gobject.IO_HUP | gobject.IO_NVAL,
        on_avail)


class Terminal(object):

    def __init__(self):
        self._terminal = vte.Terminal()
        self._console = VTEConsole(self._terminal)
        self._reader = shell_pyrepl.Reader(
            shell.get_prompt, shell.readline_complete, self._console)
        self._current_reader = None
        self._shell = shell.Shell()
        self._read_input()

        self._terminal.connect("commit", self._on_user_input)
        scrollbar = gtk.VScrollbar()
        scrollbar.set_adjustment(self._terminal.get_adjustment())
        hbox = gtk.HBox()
        hbox.add(self._terminal)
        hbox.add(scrollbar)
        window = gtk.Window()
        window.add(hbox)
        window.show_all()

    def _read_input(self):
        self._shell.job_controller.shell_to_foreground()
        self._reader.prepare()
        self._reader.refresh()
        self._current_reader = self._on_readline_input

    def _on_user_input(self, widget_unused, data, size):
        self._current_reader(data)

    def _on_readline_input(self, data):
        # This is pretty ugly.  This mixture of push and pull driven
        # styles doesn't work very well.
        for key in data:
            self._console.event_queue.push(key)
        while not self._console.event_queue.empty():
            self._reader.clear_error()
            event = self._console.event_queue.get()
            if event is not None:
                self._reader.input_trans.push(event)
                cmd = self._reader.input_trans.get()
                if cmd is not None:
                    try:
                        self._reader.do_cmd(cmd)
                    except EOFError:
                        self._exit()
        if self._reader.finished:
            self._reader.restore()
            self._process_input(self._reader.get_buffer())

    def _process_input(self, line):
        master_fd, slave_fd = openpty()
        forward_output_to_terminal(master_fd, self._terminal)
        def on_input(data):
            os.write(master_fd.fileno(), data)
        self._current_reader = on_input
        fds = {0: slave_fd, 1: slave_fd, 2: slave_fd}
        try:
            # TODO: don't run a nested event loop here.
            self._shell.run_command(line, fds)
        except Exception:
            traceback.print_exc()
        self._read_input()

    def _exit(self):
        gtk.main_quit()


def main():
    Terminal()
    gtk.main()


if __name__ == "__main__":
    main()
