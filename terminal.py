#!/usr/bin/env python

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
import signal
import struct
import termios
import time
import traceback

import gobject
import gtk
import vte

import pyrepl.unix_console

import jobcontrol
import shell
import shell_event
import shell_pyrepl


def openpty():
    master_fd, slave_fd = os.openpty()
    return os.fdopen(master_fd, "w"), os.fdopen(slave_fd, "w")


class VTEConsole(pyrepl.unix_console.UnixConsole):

    def __init__(self, terminal):
        self._terminal = terminal
        pyrepl.unix_console.UnixConsole.__init__(self, f_in=None, term="xterm")

    # TODO: Don't use __ attributes in UnixConsole
    def flushoutput(self):
        for text, iscode in self._UnixConsole__buffer:
            self._terminal.feed(text.encode(self.encoding))
        del self._UnixConsole__buffer[:]

    def _update_size(self):
        pass


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
VTE_ERASE_AUTO = 0
VTE_ERASE_ASCII_BACKSPACE = 1
VTE_ERASE_ASCII_DELETE = 2
VTE_ERASE_DELETE_SEQUENCE = 3
VTE_ERASE_TTY = 4


class TerminalWidget(object):

    def __init__(self, parts):
        self._terminal = vte.Terminal()
        # set_pty() seems to set up backspace, but we're not using it.
        # Need ASCII_DELETE rather than ASCII_BACKSPACE if we want
        # Alt-Backspace to work.
        self._terminal.set_backspace_binding(VTE_ERASE_ASCII_DELETE)
        self._writer = JobMessageOutput(self._terminal)
        self._console = VTEConsole(self._terminal)
        parts["job_output"] = self._writer
        parts["job_tty"] = None
        parts["job_spawner"] = None # There is no single job spawner.
        environ = os.environ.copy()
        environ["TERM"] = "xterm"
        parts.setdefault("environ", environ)
        parts.setdefault("real_cwd", shell.LocalCwdTracker())
        self._shell = shell.Shell(parts)
        self._reader = shell_pyrepl.Reader(
            self._shell.get_prompt, self._shell.completer, self._console)
        self._current_reader = None
        self._current_resizer = lambda: None
        self._read_pending = lambda: None
        self._read_input()
        self._shell.job_controller.add_done_handler(self._job_done)

        self._terminal.connect("commit", self._on_user_input)
        self._terminal.connect("size_allocate", self._on_size_change)
        scrollbar = gtk.VScrollbar()
        scrollbar.set_adjustment(self._terminal.get_adjustment())
        self._hbox = gtk.HBox()
        self._hbox.pack_start(self._terminal, expand=True, fill=True)
        self._hbox.pack_start(scrollbar, expand=False)
        foreground = gtk.gdk.Color(0, 0, 0)
        background = gtk.gdk.Color(0xffff, 0xffff, 0xffff)
        palette = [gtk.gdk.Color(*colour) for colour in colours]
        self._terminal.set_colors(foreground, background, palette)
        self._terminal.set_scrollback_lines(4000)
        # VTE widget's default includes no punctuation.
        self._terminal.set_word_chars("-A-Za-z0-9,./?%&#:_")
        self._hbox.show_all()
        self._on_finished = shell_event.EventDistributor()
        self.add_finished_handler = self._on_finished.add
        self._on_attention = shell_event.EventDistributor()
        self.add_attention_handler = self._on_attention.add

    def clone(self):
        return TerminalWidget({"environ": self._shell.environ.copy(),
                               "real_cwd": self._shell.real_cwd.copy(),
                               "history": self._shell.history})

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
        self._current_resizer = lambda: None

    def _on_user_input(self, widget_unused, data, size):
        self._current_reader(data)

    def _on_size_change(self, *args):
        self._console.width = self._terminal.get_column_count()
        self._console.height = self._terminal.get_row_count()
        self._current_resizer()

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
        # Setting O_NONBLOCK shouldn't be necessary, but poll() will
        # sometimes report the FD as ready to read when reading it
        # will block.
        fcntl.fcntl(master_fd, fcntl.F_SETFL,
                    fcntl.fcntl(master_fd, fcntl.F_GETFL) | os.O_NONBLOCK)
        forward_output_to_terminal(master_fd, self._terminal)

        def on_input(data):
            os.write(master_fd.fileno(), data)

        def update_size():
            set_terminal_size(slave_fd, self._terminal.get_column_count(),
                              self._terminal.get_row_count())

        def to_foreground():
            self._current_reader = on_input
            self._current_resizer = update_size
            update_size()

        def read_pending():
            # Read pending data in case we received the process's exit
            # status before reading from the tty in the main loop.
            try:
                data = os.read(master_fd.fileno(), 4096)
            except OSError:
                pass
            else:
                self._terminal.feed(data)

        fds = {0: slave_fd, 1: slave_fd, 2: slave_fd}
        to_foreground()
        # TODO: Handle reading pending data from re-foregrounded jobs.
        self._read_pending = read_pending
        job_spawner = jobcontrol.SessionJobSpawner(
            self._shell.wait_dispatcher, self._shell.job_controller, slave_fd,
            to_foreground)
        self._shell.job_controller.stop_waiting()
        try:
            self._shell.run_job_command(line, fds, job_spawner)
        except Exception:
            self._writer.write("".join(traceback.format_exc()))
        self._shell.job_controller.check_for_done()

    def _job_done(self):
        self._on_attention.send()
        self._read_pending()
        self._read_input()

    def get_menu_items(self):
        item = gtk.MenuItem("Job To Background")
        item.connect("activate", lambda *args: self._read_input())
        return [item]


# Alert the user to completed commands that occur this much time after
# the last input.
ATTENTION_INPUT_DELAY = 1 # seconds


class TerminalWindow(object):

    def __init__(self, terminal):
        self._tabset = gtk.Notebook()
        self._tab_map = {}
        self._window = gtk.Window()
        self._window.add(self._tabset)
        self._add_tab(terminal)
        self._tabset.set_show_border(False)
        self._tabset.show_all()
        terminal.set_hints(self._window)
        self._window.connect("hide", self._on_hidden)
        self._window.connect("key_press_event", self._clear_attention)
        self._window.connect("focus_in_event", self._clear_attention)
        self._tabset.connect("switch_page", self._on_switch_tab)

    def _on_hidden(self, widged_unused):
        self._window.destroy()
        if not any(window.get_property("visible")
                   for window in gtk.window_list_toplevels()):
            gtk.main_quit()

    def _get_current_tab(self):
        tab_widget = self._tabset.get_nth_page(self._tabset.get_current_page())
        return self._tab_map[tab_widget]

    def _clear_attention(self, *args):
        self._get_current_tab()["clear_attention"]()
        self._window.set_urgency_hint(False)
        return False

    def _on_switch_tab(self, unused1, unused2, index):
        self._tab_map[self._tabset.get_nth_page(index)]["clear_attention"]()
        self._window.set_urgency_hint(False)

    def _on_button_press(self, widget_unused, event):
        self._clear_attention()
        if event.button == 3:
            self._make_menu().popup(None, None, None, event.button, event.time)
            return True
        return False

    def _make_menu(self):
        tab = self._get_current_tab()["terminal"]
        menu = gtk.Menu()
        item = gtk.MenuItem("Open _Terminal")
        def new_window(*args):
            TerminalWindow(tab.clone()).get_widget().show_all()
        item.connect("activate", new_window)
        menu.add(item)
        item = gtk.MenuItem("Open Ta_b")
        item.connect("activate", lambda *args: self._add_tab(tab.clone()))
        menu.add(item)
        for item in tab.get_menu_items():
            menu.add(item)
        menu.show_all()
        return menu

    def _update_tabs(self):
        self._tabset.set_show_tabs(len(self._tab_map) > 1)

    def _add_tab(self, terminal):
        tab_widget = terminal.get_widget()

        def clear_attention():
            label.set_markup(label_text)
            tab["last_input_time"] = time.time()

        tab = {"terminal": terminal,
               "clear_attention": clear_attention,
               "last_input_time": time.time()}
        self._tab_map[tab_widget] = tab
        self._update_tabs()
        label_text = "Terminal"
        label = gtk.Label(label_text)
        label.set_alignment(0, 0.5)
        index = self._tabset.append_page(tab_widget, label)
        self._tabset.set_tab_label_packing(tab_widget, expand=True, fill=True,
                                           pack_type=gtk.PACK_START)
        # TODO: There is a bug whereby the new VteTerminal and its
        # scroll bar do not display correctly until it is resized or
        # it produces more output.
        self._tabset.set_current_page(index)
        self._tabset.set_tab_reorderable(tab_widget, True)
        terminal.get_terminal_widget().connect("button_press_event",
                                               self._on_button_press)
        terminal.get_terminal_widget().connect(
            "popup_menu",
            lambda widget: self._make_menu().popup(None, None, None, 0, 0))

        def remove_tab():
            self._tabset.remove_page(self._tabset.page_num(tab_widget))
            del self._tab_map[tab_widget]
            self._update_tabs()
            if len(self._tab_map) == 0:
                self._window.destroy()

        def set_attention():
            if time.time() > tab["last_input_time"] + ATTENTION_INPUT_DELAY:
                self._window.set_urgency_hint(True)
                # Only highlight tabs other than the current one.
                if self._get_current_tab() != tab:
                    label.set_markup("<b>%s</b>" % label_text)

        terminal.add_finished_handler(remove_tab)
        terminal.add_attention_handler(set_attention)

    def get_widget(self):
        return self._window


def make_terminal(parts):
    return TerminalWindow(TerminalWidget(parts))


def main():
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    gtk.window_set_default_icon_name("gnome-terminal")
    parts = {"history": shell.History()}
    make_terminal(parts).get_widget().show_all()
    gtk.main()


if __name__ == "__main__":
    main()
