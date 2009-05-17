
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


class Terminal(object):

    def __init__(self):
        master_fd, slave_fd = openpty()
        self._console = pyrepl.unix_console.UnixConsole(slave_fd, slave_fd)
        self._reader = shell_pyrepl.Reader(
            shell.get_prompt, shell.readline_complete, self._console)
        self._reading_line = False
        self._fds = {0: slave_fd, 1: slave_fd, 2: slave_fd}
        self._shell = shell.Shell()
        self._read_input()

        terminal = vte.Terminal()
        terminal.connect("commit", self._on_user_input)
        terminal.set_pty(os.dup(master_fd.fileno()))
        scrollbar = gtk.VScrollbar()
        scrollbar.set_adjustment(terminal.get_adjustment())
        hbox = gtk.HBox()
        hbox.add(terminal)
        hbox.add(scrollbar)
        window = gtk.Window()
        window.add(hbox)
        window.show_all()

    def _read_input(self):
        self._shell.job_controller.shell_to_foreground()
        self._reader.prepare()
        self._reader.refresh()
        self._reading_line = True

    def _on_user_input(self, widget_unused, data, size):
        if not self._reading_line:
            return
        # This is pretty ugly.  This mixture of push and pull driven
        # styles doesn't work very well.
        for key in data:
            self._console.event_queue.push(key)
        while not self._console.event_queue.empty():
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
            self._reading_line = False
            self._reader.restore()
            self._process_input(self._reader.get_buffer())

    def _process_input(self, line):
        try:
            # TODO: don't run a nested event loop here.
            self._shell.run_command(line, self._fds)
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
