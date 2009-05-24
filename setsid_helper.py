
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


# In order for Ctrl-C and Ctrl-Z to work on subprocesses running under
# a newly-created tty, this needs to be set as their controlling tty.
# In order to do that, we must first do setsid() to detach from the
# existing tty.  This creates a new session, and makes the current
# process the session leader (for which pid == session ID).
#
# However, session leaders cannot be stopped with Ctrl-Z, so we need
# an intermediate process which does setsid() and then spawns child
# processes.
#
# wait() only returns statuses for immediate children, so we need to
# forward wait statuses to our parent.
#
# We use fork+exec rather than fork so that we do not keep memory
# alive unnecessarily.

import fcntl
import os
import signal
import sys
import termios

import gobject

import jobcontrol
import shell


class NonOwningFDWrapper(object):

    def __init__(self, fd):
        self._fd = fd

    def fileno(self):
        return self._fd


def spawn(specs, pipe_fd, tty_fd):
    # We do not want to get killed by Ctrl-C.  We should only exit
    # when the child processes have exited.
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    # We can get these signals when setting the status of child
    # processes.  Ignore them otherwise we'll get wedged!
    signal.signal(signal.SIGTTIN, signal.SIG_IGN)
    signal.signal(signal.SIGTTOU, signal.SIG_IGN)

    pipe = os.fdopen(pipe_fd, "w", 0)
    # Detach from controlling tty and create new session.
    os.setsid()
    # Set controlling tty.
    fcntl.ioctl(tty_fd, termios.TIOCSCTTY, 0)
    pgroup = jobcontrol.ProcessGroup(True, NonOwningFDWrapper(tty_fd))
    pids = []
    for spec in specs:
        spec["pgroup"] = pgroup
        spec["fds"] = dict((dest_fd, NonOwningFDWrapper(fd))
                            for dest_fd, fd in spec["fds"].iteritems())
        pids.append(shell.spawn_subprocess(spec))
    shell.close_fds([pipe_fd])
    os.chdir("/") # Don't keep directory FD alive via cwd.
    pipe.write("%s\n" % repr(pids))
    while True:
        try:
            pid, status = os.waitpid(-1, os.WUNTRACED)
        except OSError:
            break
        pipe.write("%s\n" % repr((pid, status)))


def run(proc_specs, tty_fd, callback):
    pipe_read, pipe_write = jobcontrol.make_pipe()

    proc_specs = [spec.copy() for spec in proc_specs]
    for spec in proc_specs:
        spec["fds"] = dict((dest_fd, fd.fileno())
                           for dest_fd, fd in spec["fds"].iteritems())
        if "cwd_fd" in spec:
            spec["cwd_fd"] = spec["cwd_fd"].fileno()
    args = (proc_specs, pipe_write.fileno(), tty_fd.fileno())
    # Exposes icky internal stuff in argv, visible in /proc.
    # Send across pipe instead?
    argv = ["python", __file__, repr(args)]

    def in_subprocess():
        os.execv(sys.executable, argv)

    helper_pid = shell.in_forked(in_subprocess)
    # Forking and sending pids should be prompt, so we can block here.
    pids = eval(pipe_read.readline(), {})

    def on_ready(*args):
        # TODO: This is not really safe because this reading is
        # buffered.  It could read multiple messages but we will only
        # handle one.
        line = pipe_read.readline()
        if len(line) > 0:
            message = eval(line, {})
            callback(*message)
            return True
        else:
            return False

    gobject.io_add_watch(pipe_read.fileno(), gobject.IO_IN | gobject.IO_HUP,
                         on_ready)
    return helper_pid, pids


def main(args):
    spawn(*eval(args[0], {}))


if __name__ == "__main__":
    main(sys.argv[1:])
