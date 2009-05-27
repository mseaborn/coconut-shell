
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
import fcntl
import struct
import traceback

import gobject
import gtk
import vte

import pyrepl.unix_console

import jobcontrol
import shell
import shell_pyrepl


class EventDistributor(object):

    def __init__(self):
        self._callbacks = []

    def add(self, callback):
        self._callbacks.append(callback)

    def send(self, *args):
        for callback in self._callbacks:
            callback(*args)


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


class JobMessageOutput(object):

    def __init__(self, terminal):
        self._terminal = terminal

    def write(self, data):
        self._terminal.feed(data.replace("\n", "\n\r"))


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


def set_terminal_size(tty_fd, width, height):
    fcntl.ioctl(tty_fd, termios.TIOCSWINSZ,
                struct.pack("HHHH", height, width, 0, 0))


# Tango theme, from gnome-terminal's terminal-profile.c.
colours = [
    (0x2e2e, 0x3434, 0x3636),
    (0xcccc, 0x0000, 0x0000),
    (0x4e4e, 0x9a9a, 0x0606),
    (0xc4c4, 0xa0a0, 0x0000),
    (0x3434, 0x6565, 0xa4a4),
    (0x7575, 0x5050, 0x7b7b),
    (0x0606, 0x9820, 0x9a9a),
    (0xd3d3, 0xd7d7, 0xcfcf),
    (0x5555, 0x5757, 0x5353),
    (0xefef, 0x2929, 0x2929),
    (0x8a8a, 0xe2e2, 0x3434),
    (0xfcfc, 0xe9e9, 0x4f4f),
    (0x7272, 0x9f9f, 0xcfcf),
    (0xadad, 0x7f7f, 0xa8a8),
    (0x3434, 0xe2e2, 0xe2e2),
    (0xeeee, 0xeeee, 0xecec),
    ]


# Constants apparently missing from Python bindings.
VTE_ERASE_ASCII_BACKSPACE = 1


class TerminalWidget(object):

    def __init__(self, make_template=lambda: {}):
        self._terminal = vte.Terminal()
        # set_pty() seems to set up backspace, but we're not using it.
        self._terminal.set_backspace_binding(VTE_ERASE_ASCII_BACKSPACE)
        self._console = VTEConsole(self._terminal)
        parts = make_template()
        parts["job_output"] = JobMessageOutput(self._terminal)
        parts["job_tty"] = None
        parts["job_spawner"] = None # There is no single job spawner.
        parts["real_cwd"] = shell.LocalCwdTracker()
        self._shell = shell.Shell(parts)
        self._reader = shell_pyrepl.Reader(
            self._shell.get_prompt, self._shell.completer, self._console)
        self._current_reader = None
        self._read_input()

        self._terminal.connect("commit", self._on_user_input)
        scrollbar = gtk.VScrollbar()
        scrollbar.set_adjustment(self._terminal.get_adjustment())
        self._hbox = gtk.HBox()
        self._hbox.pack_start(self._terminal, expand=True, fill=True)
        self._hbox.pack_start(scrollbar, expand=False)
        foreground = gtk.gdk.Color(0, 0, 0)
        background = gtk.gdk.Color(0xffff, 0xffff, 0xffff)
        palette = [gtk.gdk.Color(*colour) for colour in colours]
        self._terminal.set_colors(foreground, background, palette)
        self._hbox.show_all()
        self._on_finished = EventDistributor()
        self.add_finished_handler = self._on_finished.add

    def set_hints(self, window):
        pad_x, pad_y = self._terminal.get_padding()
        char_x = self._terminal.get_char_width()
        char_y = self._terminal.get_char_height()
        window.set_geometry_hints(
            self._terminal,
            min_width=pad_x + char_x * 2,
            min_height=pad_y + char_y * 2,
            max_width=-1, max_height=-1,
            base_width=pad_x, base_height=pad_y,
            width_inc=char_x, height_inc=char_y,
            min_aspect=-1, max_aspect=-1)
        window.set_focus(self._terminal)

    def get_widget(self):
        return self._hbox

    def get_terminal_widget(self):
        return self._terminal

    def _read_input(self):
        self._shell.job_controller.print_messages()
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
                        self._on_finished.send()
        if self._reader.finished:
            self._reader.restore()
            self._process_input(self._reader.get_buffer())

    def _process_input(self, line):
        master_fd, slave_fd = openpty()
        set_terminal_size(slave_fd, self._terminal.get_column_count(),
                          self._terminal.get_row_count())
        forward_output_to_terminal(master_fd, self._terminal)

        def on_input(data):
            os.write(master_fd.fileno(), data)

        def to_foreground():
            self._current_reader = on_input

        fds = {0: slave_fd, 1: slave_fd, 2: slave_fd}
        to_foreground()
        job_spawner = jobcontrol.SessionJobSpawner(
            self._shell.wait_dispatcher, self._shell.job_controller, slave_fd,
            to_foreground)
        try:
            # TODO: don't run a nested event loop here.
            self._shell.run_job_command(line, fds, job_spawner)
        except Exception:
            traceback.print_exc()
        self._read_input()

    def get_menu_items(self):
        item = gtk.MenuItem("Job To Background")
        item.connect("activate", lambda *args: self._read_input())
        return [item]


class TerminalWindow(object):

    def __init__(self):
        self._tabset = gtk.Notebook()
        self._tabs = []
        self._window = gtk.Window()
        self._window.add(self._tabset)
        terminal = self._add_tab()
        self._tabset.set_show_border(False)
        self._tabset.show_all()
        terminal.set_hints(self._window)
        self._window.connect(
            "popup_menu",
            lambda widget: self._make_menu().popup(None, None, None, 0, 0))
        self._window.connect("hide", self._on_hidden)

    def _on_hidden(self, widged_unused):
        self._window.destroy()
        if not any(window.get_property("visible")
                   for window in gtk.window_list_toplevels()):
            gtk.main_quit()

    def _menu_click(self, widget_unused, event):
        if event.button == 3:
            self._make_menu().popup(None, None, None, event.button, event.time)
            return True
        return False

    def _make_menu(self):
        menu = gtk.Menu()
        item = gtk.MenuItem("Open _Terminal")
        item.connect("activate",
                     lambda *args: TerminalWindow().get_widget().show_all())
        menu.add(item)
        item = gtk.MenuItem("Open Ta_b")
        item.connect("activate", lambda *args: self._add_tab())
        menu.add(item)
        tab = self._tabs[self._tabset.get_current_page()]
        for item in tab.get_menu_items():
            menu.add(item)
        menu.show_all()
        return menu

    def _update_tabs(self):
        self._tabset.set_show_tabs(len(self._tabs) > 1)

    def _add_tab(self):
        terminal = TerminalWidget()
        self._tabs.append(terminal)
        self._update_tabs()
        index = self._tabset.append_page(terminal.get_widget(),
                                         gtk.Label("Terminal"))
        # TODO: There is a bug whereby the new VteTerminal and its
        # scroll bar do not display correctly until it is resized or
        # it produces more output.
        self._tabset.set_current_page(index)
        terminal.get_terminal_widget().connect("button_press_event",
                                               self._menu_click)

        def remove_tab():
            index = self._tabs.index(terminal)
            self._tabset.remove_page(index)
            self._tabs.pop(index)
            self._update_tabs()
            if len(self._tabs) == 0:
                self._window.destroy()

        terminal.add_finished_handler(remove_tab)
        return terminal

    def get_widget(self):
        return self._window


def main():
    TerminalWindow().get_widget().show_all()
    gtk.main()


if __name__ == "__main__":
    main()
