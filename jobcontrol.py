
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
import threading

import gobject

import setsid_helper
import shell_event
import shell_spawn


class WaitDispatcher(object):

    # glib currently does not support using WUNTRACED with waitpid()
    # to get stopped statuses, so work around this by doing waitpid()
    # inside threads.  We cannot use child_watch_add() at the same
    # time because that causes glib to set the SA_NOCLDSTOP flag which
    # stops WUNTRACED from working.
    # See also <http://bugzilla.gnome.org/show_bug.cgi?id=562501>.

    def __init__(self):
        self._queue = []
        read_fd, self._write_fd = shell_spawn.make_pipe()
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


class SessionHelperDispatcher(object):

    def __init__(self):
        self._handlers = {}

    def handle_status(self, pid, status):
        if os.WIFEXITED(status) or os.WIFSIGNALED(status):
            self._handlers.pop(pid)(status)
        else:
            self._handlers[pid](status)

    def add_handler(self, pid, callback):
        assert pid not in self._handlers
        self._handlers[pid] = callback


class ChildProcess(object):

    def __init__(self, dispatcher, pid):
        self.pid = pid
        self.state = "running"
        self._status_handlers = shell_event.EventDistributor()
        self.add_status_handler = self._status_handlers.add
        dispatcher.add_handler(pid, self._status_handler)

    def _status_handler(self, status):
        if os.WIFSTOPPED(status):
            self.state = "stopped"
        else:
            self.state = "finished"
        self._status_handlers.send(status)


class Job(object):

    def __init__(self, procs, pgid, cmd_text, to_foreground):
        self.procs = procs
        self.pgid = pgid
        self.state = "running"
        self.cmd_text = cmd_text
        self.to_foreground = to_foreground
        self._on_state_change = shell_event.EventDistributor()
        self.add_state_change_handler = self._on_state_change.add
        for proc in self.procs:
            proc.add_status_handler(self._process_status_handler)

    def _process_status_handler(self, unused_status):
        old_state = self.state
        self.state = self._get_state()
        if self.state != old_state:
            self._on_state_change.send()

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


state_map = {"running": "Running",
             "stopped": "Stopped",
             "finished": "Done"}


class SimpleJobSpawner(object):

    def start_job(self, job_procs, is_foreground, cmd_text):
        for spec in job_procs:
            spec["pgroup"] = shell_spawn.NullProcessGroup()
            del spec
        pids = map(shell_spawn.spawn_subprocess, job_procs)
        # We must ensure that FDs are dropped before waiting.
        job_procs[:] = []
        if is_foreground:
            for pid in pids:
                os.waitpid(pid, 0)


class ProcessGroupJobSpawner(object):

    def __init__(self, dispatcher, job_controller, tty_fd):
        self._dispatcher = dispatcher
        self._job_controller = job_controller
        self._tty_fd = tty_fd

    # Start a job in a new process group but same session.
    def start_job(self, job_procs, is_foreground, cmd_text):
        pgroup = shell_spawn.ProcessGroup(is_foreground, self._tty_fd)
        pids = []
        for spec in job_procs:
            spec["pgroup"] = pgroup
            pids.append(shell_spawn.spawn_subprocess(spec))
            del spec
        # We must ensure that FDs are dropped before any waiting.
        job_procs[:] = []
        procs = [ChildProcess(self._dispatcher, proc) for proc in pids]
        pgid = pgroup.get_pgid()

        def to_foreground():
            os.tcsetpgrp(self._tty_fd.fileno(), pgid)

        job = Job(procs, pgroup.get_pgid(), cmd_text, to_foreground)
        self._job_controller.add_job(job, is_foreground)


class SessionJobSpawner(object):

    def __init__(self, dispatcher, job_controller, tty_fd, to_foreground):
        self._dispatcher = dispatcher
        self._job_controller = job_controller
        self._tty_fd = tty_fd
        self._to_foreground = to_foreground

    # Start a job with a new controlling tty.
    def start_job(self, job_procs, is_foreground, cmd_text):
        dispatcher_for_job = SessionHelperDispatcher()
        helper_pid, pids = setsid_helper.run(
            job_procs, self._tty_fd, dispatcher_for_job.handle_status)
        # Wait for helper process so that it doesn't become a zombie.
        self._dispatcher.add_handler(helper_pid, lambda status: None)
        # We must ensure that FDs are dropped before any waiting.
        job_procs[:] = []
        procs = [ChildProcess(dispatcher_for_job, proc) for proc in pids]
        pgid = pids[0]
        job = Job(procs, pgid, cmd_text, self._to_foreground)
        self._job_controller.add_job(job, is_foreground)


class JobController(object):

    def __init__(self, dispatcher, output, tty_fd):
        self._dispatcher = dispatcher
        self._output = output
        self._tty_fd = tty_fd
        self._state_changed = set()
        self.jobs = {}
        self._awaiting_job = None
        self._done_handlers = shell_event.EventDistributor()
        self.add_done_handler = self._done_handlers.add

    def add_job(self, job, is_foreground):
        def on_state_change():
            self._state_changed.add((job_id, job))
            if self._awaiting_job == job_id and job.state != "running":
                if job.state == "finished":
                    self._state_changed.remove((job_id, job))
                    del self.jobs[job_id]
                self._done_handlers.send()
                self._awaiting_job = None

        job_id = max([0] + self.jobs.keys()) + 1
        self.jobs[job_id] = job
        job.add_state_change_handler(on_state_change)
        if is_foreground:
            self._wait_for_job(job_id, job)
        else:
            self._output.write("[%s] %i\n" % (job_id, job.pgid))

    def check_for_done(self):
        if self._awaiting_job is None:
            self._done_handlers.send()

    def stop_waiting(self):
        self._awaiting_job = None

    def _wait_for_job(self, job_id, job):
        self._awaiting_job = job_id

    def shell_to_foreground(self):
        # The shell should never accidentally stop itself.
        signal.signal(signal.SIGTTIN, signal.SIG_IGN)
        signal.signal(signal.SIGTTOU, signal.SIG_IGN)
        if self._tty_fd is not None:
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

    def _list_jobs(self, new_job, spec):
        stdout = spec["fds"][1]
        for job_id, job in sorted(self.jobs.iteritems()):
            stdout.write("[%s] %s  %s\n" % (job_id, state_map[job.state],
                                            job.cmd_text))

    def _job_from_args(self, spec):
        args = spec["args"]
        if len(args) == 0:
            job_id = max(self.jobs)
        elif len(args) == 1:
            job_id = int(args[0])
        else:
            raise Exception("Too many arguments")
        return job_id, self.jobs[job_id]

    def _bg_job(self, job, spec):
        job_id, job = self._job_from_args(spec)
        job.resume()

    def _fg_job(self, job, spec):
        job_id, job = self._job_from_args(spec)
        job.to_foreground()
        job.resume()
        self._wait_for_job(job_id, job)

    def get_builtins(self):
        return {"jobs": self._list_jobs,
                "bg": self._bg_job,
                "fg": self._fg_job}
