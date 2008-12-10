
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
import signal
import sys
import threading

import gobject


def make_pipe():
    read_fd, write_fd = os.pipe()
    return os.fdopen(read_fd, "r", 0), os.fdopen(write_fd, "w", 0)


class WaitDispatcher(object):

    # glib currently does not support using WUNTRACED with waitpid()
    # to get stopped statuses, so work around this by doing waitpid()
    # inside threads.  We cannot use child_watch_add() at the same
    # time because that causes glib to set the SA_NOCLDSTOP flag which
    # stops WUNTRACED from working.
    # See also <http://bugzilla.gnome.org/show_bug.cgi?id=562501>.

    def __init__(self):
        self._queue = []
        read_fd, self._write_fd = make_pipe()
        def on_ready(*args):
            read_fd.read(1)
            while True:
                try:
                    func = self._queue.pop(0)
                except IndexError:
                    break
                else:
                    func()
            return True
        # Need to initialise threads otherwise pygobject won't drop
        # the Python GIL while doing an iteration of the glib loop.
        gobject.threads_init()
        gobject.io_add_watch(read_fd.fileno(), gobject.IO_IN, on_ready)

    def add_handler(self, pid, callback):
        assert isinstance(pid, int), pid
        def enqueue_status(status):
            self._queue.append(lambda: callback(status))
            self._write_fd.write("x")
        def in_thread():
            while True:
                pid2, status = os.waitpid(pid, os.WUNTRACED)
                enqueue_status(status)
                if not os.WIFSTOPPED(status):
                    break
        thread = threading.Thread(target=in_thread)
        thread.setDaemon(True)
        thread.start()

    def once(self, may_block):
        gobject.main_context_default().iteration(may_block)

    def read_pending(self):
        while True:
            if not self.once(may_block=False):
                break


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

    def __init__(self, dispatcher, procs, pgid, on_state_change, cmd_text):
        self.procs = [ChildProcess(proc) for proc in procs]
        self.pgid = pgid
        self.state = "running"
        self.cmd_text = cmd_text
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


state_map = {"running": "Running",
             "stopped": "Stopped",
             "finished": "Done"}


class JobController(object):

    def __init__(self, dispatcher, output):
        self._dispatcher = dispatcher
        self._output = output
        self._state_changed = set()
        self.jobs = {}
        self._tty_fd = sys.stdout

    def create_job(self, is_foreground, cmd_text):
        launcher = ProcessGroup(is_foreground, tty_fd=self._tty_fd)

        def add_job(procs):
            if len(procs) == 0:
                return
            def on_state_change():
                self._state_changed.add((job_id, job))
            job_id = max([0] + self.jobs.keys()) + 1
            job = Job(self._dispatcher, procs, launcher.get_pgid(),
                      on_state_change, cmd_text)
            self.jobs[job_id] = job
            if is_foreground:
                self._wait_for_job(job_id, job)
            else:
                self._output.write("[%s] %i\n" % (job_id, job.pgid))
        return launcher, add_job

    def _wait_for_job(self, job_id, job):
        while job.state == "running":
            self._dispatcher.once(may_block=True)
        if job.state == "finished":
            # Don't print the state change message for the job
            # that we have been waiting for.
            self._state_changed.remove((job_id, job))
            del self.jobs[job_id]

    def shell_to_foreground(self):
        # The shell should never accidentally stop itself.
        signal.signal(signal.SIGTTIN, signal.SIG_IGN)
        signal.signal(signal.SIGTTOU, signal.SIG_IGN)
        os.tcsetpgrp(self._tty_fd.fileno(), os.getpgrp())

    def _job_status_change(self, job_id, job):
        self._output.write("[%s]+ %s  %s\n" % (job_id, state_map[job.state],
                                               job.cmd_text))

    def print_messages(self):
        self._dispatcher.read_pending()
        for job_id, job in sorted(self._state_changed):
            if job.state == "stopped":
                self._job_status_change(job_id, job)
            elif job.state == "finished":
                self._job_status_change(job_id, job)
                del self.jobs[job_id]
        self._state_changed.clear()

    def _list_jobs(self, args, pgroup, fds):
        stdout = fds[1]
        for job_id, job in sorted(self.jobs.iteritems()):
            stdout.write("[%s] %s  %s\n" % (job_id, state_map[job.state],
                                            job.cmd_text))

    def _job_from_args(self, args):
        if len(args) == 0:
            job_id = max(self.jobs)
        elif len(args) == 1:
            job_id = int(args[0])
        else:
            raise Exception("Too many arguments")
        return job_id, self.jobs[job_id]

    def _bg_job(self, args, pgroup, fds):
        job_id, job = self._job_from_args(args)
        job.resume()

    def _fg_job(self, args, pgroup, fds):
        job_id, job = self._job_from_args(args)
        os.tcsetpgrp(self._tty_fd.fileno(), job.pgid)
        job.resume()
        self._wait_for_job(job_id, job)

    def get_builtins(self):
        return {"jobs": self._list_jobs,
                "bg": self._bg_job,
                "fg": self._fg_job}
