
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

import sys
import traceback

import gtk


# This is separate so that we can monkey-patch it during tests.
def show_all(widget):
    widget.show_all()


def except_hook(*exc_info):
    # Display an error dialog but also send errors to stderr.
    title = "Terminal: Unexpected error"
    text = "".join(traceback.format_exception(*exc_info))
    sys.stderr.write(text)
    dialog = gtk.MessageDialog(buttons=gtk.BUTTONS_CLOSE)
    dialog.set_title(title)
    dialog.set_property("text", title)
    dialog.set_property("secondary_text", text.strip("\n"))
    dialog.connect("response", lambda *args: dialog.destroy())
    show_all(dialog)


def set_excepthook():
    sys.excepthook = except_hook
