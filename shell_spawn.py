
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

import errno
import gc
import itertools
import os
import signal
import sys
import traceback


def set_up_signals():
    # Python changes signal handler settings on startup, including
    # setting SIGPIPE to SIG_IGN (ignore), which gets inherited by
    # child processes.  I am surprised this does not cause problems
    # more often.  Change the setting back.
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    signal.signal(signal.SIGINT, signal.SIG_DFL)


def in_forked(func):
    pid = os.fork()
    if pid == 0:
        try:
            func()
        finally:
            os._exit(1)
    return pid

MAXFD = os.sysconf("SC_OPEN_MAX")

def close_fds(keep_fds):
    for fd in xrange(MAXFD):
        if fd not in keep_fds:
            try:
                os.close(fd)
            except OSError, exn:
                if exn.errno != errno.EBADF:
                    raise

def set_up_fds(fds):
    involved_fds = set()
    for fd_dest, fd in fds.iteritems():
        involved_fds.add(fd_dest)
        involved_fds.add(fd.fileno())
    fds_with_temps = zip(fds.iteritems(),
                         (fd for fd in itertools.count()
                          if fd not in involved_fds))
    for (fd_dest, fd), temp_fd in fds_with_temps:
        os.dup2(fd.fileno(), temp_fd)
    for (fd_dest, fd), temp_fd in fds_with_temps:
        os.dup2(temp_fd, fd_dest)
    close_fds(fds)


subprocess_keys = set(["args", "fds", "environ", "cwd_fd", "pgroup",
                       "uid", "gid", "groups"])

def spawn_subprocess(spec):
    args = spec["args"]
    def in_subprocess():
        try:
            if "cwd_fd" in spec:
                os.fchdir(spec["cwd_fd"])
            # Disable GC so that Python does not try to close FDs
            # that we have closed ourselves, which prints "close
            # failed: [Errno 9] Bad file descriptor" errors.
            gc.disable()
            set_up_signals()
            spec["pgroup"].init_process(os.getpid())
            set_up_fds(spec["fds"])
            if "groups" in spec:
                os.setgroups(spec["groups"])
            if "gid" in spec:
                os.setgid(spec["gid"])
            if "uid" in spec:
                os.setuid(spec["uid"])
            try:
                os.execvpe(args[0], args, spec.get("environ", os.environ))
            except OSError:
                sys.stderr.write("%s: command not found\n" % args[0])
        except:
            traceback.print_exc()
    pid = in_forked(in_subprocess)
    spec["pgroup"].init_process(pid)
    return pid
