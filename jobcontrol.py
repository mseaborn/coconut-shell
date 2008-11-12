
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

import errno
import os
import subprocess
import signal
import sys


class WaitDispatcher(object):

    def __init__(self):
        self._by_pid = {}

    def add_handler(self, pid, callback):
        self._by_pid[pid] = callback

    def once(self, may_block):
        flags = 0
        if not may_block:
            flags |= os.WNOHANG
        pid, status = os.waitpid(-1, flags | os.WUNTRACED)
        if pid in self._by_pid:
            self._by_pid[pid](status)
            if not os.WIFSTOPPED(status):
                del self._by_pid[pid]
        return pid != 0

    def read_pending(self):
        while True:
            try:
                if not self.once(may_block=False):
                    break
            except OSError, exn:
                if exn.errno == errno.ECHILD:
                    break
                else:
                    raise


class ChildProcess(object):

    def __init__(self, pid):
        self.pid = pid
        self.state = "running"

    def update(self, status):
        if os.WIFSTOPPED(status):
            self.state = "stopped"
        else:
            self.state = "finished"


class Job(object):

    def __init__(self, dispatcher, procs, pgid, on_state_change):
        self.procs = [ChildProcess(proc.pid) for proc in procs]
        self.pgid = pgid
        self.state = "running"
        for proc in self.procs:
            self._add_handler(dispatcher, proc, on_state_change)

    def _add_handler(self, dispatcher, proc, on_state_change):
        def handler(status):
            proc.update(status)
            old_state = self.state
            self.state = self._get_state()
            if self.state != old_state:
                on_state_change()
        dispatcher.add_handler(proc.pid, handler)

    def _get_state(self):
        if all(proc.state == "finished" for proc in self.procs):
            return "finished"
        elif any(proc.state == "running" for proc in self.procs):
            return "running"
        else:
            return "stopped"

    def send_signal(self, signal_number):
        os.kill(-self.pgid, signal_number)

    def resume(self):
        self.send_signal(signal.SIGCONT)
        for proc in self.procs:
            proc.state = "running"
        self.state = "running"


class ProcessGroup(object):

    def __init__(self, foreground, tty_fd):
        self._pgid = None
        self._foreground = foreground
        self._tty_fd = tty_fd

    def init_process(self, pid):
        # This method needs to be called in both the parent and child
        # processes to avoid race conditions.
        if self._pgid is None:
            self._pgid = pid
        try:
            os.setpgid(pid, self._pgid)
        except OSError, exn:
            # We get EACCES if the child process has already called
            # execve(), by which time a second setpgid() is unnecessary.
            if exn.errno != errno.EACCES:
                raise
        if self._foreground:
            # We need to do this in the child process to avoid a race
            # condition.
            # Alternatively we could stop the child processes after
            # forking them and restart them after changing settings.
            try:
                os.tcsetpgrp(self._tty_fd.fileno(), self._pgid)
            except OSError:
                pass

    def get_pgid(self):
        return self._pgid


class JobController(object):

    def __init__(self, dispatcher, output):
        self._dispatcher = dispatcher
        self._output = output
        self._state_changed = set()
        self.jobs = {}

    def create_job(self, is_foreground):
        launcher = ProcessGroup(is_foreground, tty_fd=sys.stdout)

        def add_job(procs):
            if len(procs) == 0:
                return
            def on_state_change():
                self._state_changed.add((job_id, job))
            job_id = max([0] + self.jobs.keys()) + 1
            job = Job(self._dispatcher, procs, launcher.get_pgid(),
                      on_state_change)
            self.jobs[job_id] = job
            if is_foreground:
                while job.state == "running":
                    self._dispatcher.once(may_block=True)
                if job.state == "finished":
                    # Don't print the state change message for the job
                    # that we have been waiting for.
                    self._state_changed.remove((job_id, job))
                    del self.jobs[job_id]
            else:
                self._output.write("[%s] %i\n" % (job_id, job.pgid))
        return launcher, add_job

    def shell_to_foreground(self):
        # The shell should never accidentally stop itself.
        signal.signal(signal.SIGTTIN, signal.SIG_IGN)
        signal.signal(signal.SIGTTOU, signal.SIG_IGN)
        os.tcsetpgrp(sys.stdout.fileno(), os.getpgrp())

    def print_messages(self):
        self._dispatcher.read_pending()
        for job_id, job in sorted(self._state_changed):
            if job.state == "stopped":
                self._output.write("[%s]+ Stopped\n" % job_id)
            elif job.state == "finished":
                self._output.write("[%s]+ Done\n" % job_id)
                del self.jobs[job_id]
        self._state_changed.clear()

    def _list_jobs(self, stdout):
        state_map = {"running": "Running",
                     "stopped": "Stopped",
                     "finished": "Done"}
        for job_id, job in sorted(self.jobs.iteritems()):
            stdout.write("[%s] %s\n" % (job_id, state_map[job.state]))

    def get_builtins(self):
        return {"jobs": self._list_jobs}
