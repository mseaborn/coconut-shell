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

import shell


def main():
    sqldb = shell.History().sqldb
    cursor = sqldb.execute(
        "SELECT command, time, cwd_path FROM history ORDER BY time")
    for command, time, cwd in cursor:
        cwd = shell.unexpanduser(cwd)
        print "%s [%s]: %s" % (time, cwd, command)


if __name__ == "__main__":
    main()
