#!/usr/bin/env python

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
import gc
import glob
import itertools
import os
import pwd
import readline
import signal
import socket
import string
import sys
import traceback

import gobject
import pyparsing as parse

import jobcontrol


FILENO_STDIN = 0
FILENO_STDOUT = 1
FILENO_STDERR = 2


def set_up_signals():
    # Python changes signal handler settings on startup, including
    # setting SIGPIPE to SIG_IGN (ignore), which gets inherited by
    # child processes.  I am surprised this does not cause problems
    # more often.  Change the setting back.
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    signal.signal(signal.SIGINT, signal.SIG_DFL)


class StringArgument(object):

    def __init__(self, string):
        self._string = string

    def eval(self, args, fds):
        args.append(self._string)


class ExpandStringArgument(object):

    def __init__(self, string):
        self._string = string
        # TODO: should check for "[" and "]" as well
        # This is an optimisation.  If this is not a glob expression,
        # checking the filesystem would be pointless.
        self._do_glob = "*" in string or "?" in string

    def eval(self, args, fds):
        string = os.path.expanduser(self._string)
        if self._do_glob:
            matches = sorted(glob.glob(string))
            if len(matches) > 0:
                args.extend(matches)
                return
        args.append(string)


class RedirectFD(object):

    def __init__(self, fd1, fd2):
        self._fd1 = fd1
        self._fd2 = fd2

    def eval(self, args, fds):
        fds[self._fd1] = fds[self._fd2]


class RedirectFile(object):

    def __init__(self, dest_fd, mode, filename):
        self._dest_fd = dest_fd
        self._mode = mode
        self._filename = filename

    def eval(self, args, fds):
        fds[self._dest_fd] = open(self._filename, self._mode)


class CommandExp(object):

    def __init__(self, args):
        self._args = args

    def run(self, launcher, pgroup, fds):
        evaled_args = []
        fds = fds.copy()
        for arg in self._args:
            arg.eval(evaled_args, fds)
        proc = launcher.spawn(evaled_args, pgroup, fds)
        if proc is None:
            return []
        else:
            return [proc]


class PipelineExp(object):

    def __init__(self, cmd1, cmd2):
        self._cmd1 = cmd1
        self._cmd2 = cmd2

    def run(self, launcher, pgroup, fds):
        pipe_read_fd, pipe_write_fd = os.pipe()
        fds1 = fds.copy()
        fds2 = fds.copy()
        fds1[FILENO_STDOUT] = os.fdopen(pipe_write_fd, "w")
        fds2[FILENO_STDIN] = os.fdopen(pipe_read_fd, "r")
        procs = []
        procs.extend(self._cmd1.run(launcher, pgroup, fds1))
        procs.extend(self._cmd2.run(launcher, pgroup, fds2))
        return procs


class JobExp(object):

    def __init__(self, cmd, is_foreground, cmd_text):
        self._cmd = cmd
        self._is_foreground = is_foreground
        self._cmd_text = cmd_text

    def run(self, job_controller, launcher, fds):
        pgroup, add_job = job_controller.create_job(self._is_foreground,
                                                    self._cmd_text)
        procs = self._cmd.run(launcher, pgroup, fds)
        add_job(procs)


# TODO: doesn't handle backslash right
double_quoted = parse.QuotedString(quoteChar='"', escChar='\\', multiline=True)
single_quoted = parse.QuotedString(quoteChar="'", escChar='\\', multiline=True)
quoted_argument = (double_quoted | single_quoted) \
    .setParseAction(lambda text, loc, arg: StringArgument(get_one(arg)))

special_chars = "|&\"'<>"
bare_chars = "".join(sorted(set(parse.srange("[a-zA-Z0-9]") +
                                string.punctuation)
                            - set(special_chars)))
bare_argument = parse.Word(bare_chars) \
    .setParseAction(lambda text, loc, arg: ExpandStringArgument(get_one(arg)))

fd_number = parse.Word(parse.srange("[0-9]")) \
    .setParseAction(lambda text, loc, args: int(get_one(args)))

redirect_arrow = (
    parse.Literal("<") \
        .setParseAction(lambda text, loc, args: [(FILENO_STDIN, "r")]) |
    parse.Literal(">") \
        .setParseAction(lambda text, loc, args: [(FILENO_STDOUT, "w")]))

redirect_lhs = (
    redirect_arrow
        .setParseAction(lambda text, loc, args: [get_one(args)]) |
    (fd_number + redirect_arrow.leaveWhitespace())
        .setParseAction(lambda text, loc, args: [(args[0], args[1][1])]))

redirect_fd = (redirect_lhs + parse.Literal("&").leaveWhitespace() +
               fd_number) \
    .setParseAction(lambda text, loc, args: RedirectFD(args[0][0], args[2]))
redirect_file = (redirect_lhs + parse.Word(bare_chars)) \
    .setParseAction(lambda text, loc, args: RedirectFile(args[0][0],
                                                         args[0][1], args[1]))

argument = redirect_fd | redirect_file | bare_argument | quoted_argument

command = (argument + parse.ZeroOrMore(argument)) \
          .setParseAction(lambda text, loc, args: CommandExp(args))

pipeline = parse.delimitedList(command, delim='|') \
           .setParseAction(lambda text, loc, cmds: reduce(PipelineExp, cmds))

job_expr = (pipeline +
            parse.Optional(parse.Literal("&").
                           setParseAction(lambda text, loc, cmds: False),
                           True)) \
           .setParseAction(lambda text, loc, (cmd, is_foreground):
                               JobExp(cmd, is_foreground, text))

top_command = parse.Optional(job_expr)


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


class Launcher(object):

    def spawn(self, args, pgroup, fds):
        def in_subprocess():
            try:
                # Disable GC so that Python does not try to close FDs
                # that we have closed ourselves, which prints "close
                # failed: [Errno 9] Bad file descriptor" errors.
                gc.disable()
                set_up_signals()
                pgroup.init_process(os.getpid())
                set_up_fds(fds)
                try:
                    os.execvp(args[0], args)
                except OSError:
                    sys.stderr.write("%s: command not found\n" % args[0])
            except:
                traceback.print_exc()
        pid = in_forked(in_subprocess)
        pgroup.init_process(pid)
        return pid


class PrefixLauncher(object):

    def __init__(self, prefix, launcher):
        self._launcher = launcher
        self._prefix = prefix

    def spawn(self, args, pgroup, fds):
        return self._launcher.spawn(self._prefix + args, pgroup, fds)


def chdir_builtin(args, pgroup, fds):
    if len(args) == 0:
        # TODO: report nicer error when HOME is not set
        chdir_logical(os.environ["HOME"])
    else:
        for arg in args:
            chdir_logical(arg)


class LauncherWithBuiltins(object):

    def __init__(self, launcher, builtins):
        self._launcher = launcher
        self._builtins = builtins

    def spawn(self, args, pgroup, fds):
        if args[0] in self._builtins:
            return self._builtins[args[0]](args[1:], pgroup, fds)
        else:
            return self._launcher.spawn(args, pgroup, fds)


class NullProcessGroup(object):

    def init_process(self, pid):
        pass


class NullJobController(object):

    def create_job(self, is_foreground, cmd_text):
        def add_job(procs):
            if is_foreground:
                for proc in procs:
                    os.waitpid(proc, 0)
        return NullProcessGroup(), add_job


def get_one(lst):
    assert len(lst) == 1, lst
    return lst[0]


def run_command(job_controller, launcher, line, fds):
    top_expr = top_command + parse.StringEnd()
    for cmd in top_expr.parseString(line):
        procs = cmd.run(job_controller, launcher, fds)


def path_starts_with(path1, path2):
    return path1 == path2 or path1.startswith(path2 + "/")


# Based on posixpath.expanduser().  In addition, it returns a function
# to reverse the expansion.
def expanduser(path):
    if not path.startswith('~'):
        return path, lambda x: x
    i = path.find('/', 1)
    if i < 0:
        i = len(path)
    if i == 1:
        if 'HOME' not in os.environ:
            userhome = pwd.getpwuid(os.getuid()).pw_dir
        else:
            userhome = os.environ['HOME']
    else:
        try:
            pwent = pwd.getpwnam(path[1:i])
        except KeyError:
            return path, lambda x: x
        userhome = pwent.pw_dir
    userhome = userhome.rstrip('/')
    def reverse(path2):
        if path_starts_with(path2, userhome):
            return path[:i] + path2[len(userhome):]
        else:
            return path2
    return userhome + path[i:], reverse


def unexpanduser(path):
    if "HOME" in os.environ:
        home = os.environ["HOME"]
        if path == home or path.startswith(home + "/"):
            return "~" + path[len(home):]
    return path


# Bash uses PWD to remember the cwd pathname before symlink expansion.
def chdir_logical(path):
    if os.path.isabs(path):
        new_cwd = path
    else:
        new_cwd = os.path.join(get_logical_cwd(), path)
    # Note that ".." is applied after symlink expansion.  We don't
    # attempt to follow Bash's behaviour here.
    os.chdir(path)
    # Only set this if chdir() succeeds.
    os.environ["PWD"] = os.path.normpath(new_cwd)


def get_logical_cwd():
    path = os.environ.get("PWD")
    if path is not None:
        try:
            stat1 = os.stat(path)
            stat2 = os.stat(".")
        except OSError:
            pass
        else:
            if (stat1.st_dev == stat2.st_dev and
                stat1.st_ino == stat2.st_ino):
                return path
    return os.getcwd()


def readline_complete(string):
    filename, reverse_expansion = expanduser(string)
    for filename in sorted(glob.glob(filename + "*")):
        if os.path.isdir(filename):
            # This treats symlinks to directories differently from Bash,
            # but this might be considered an improvement.
            yield reverse_expansion(filename) + "/"
        else:
            yield reverse_expansion(filename)


def readline_complete_wrapper(string, index):
    try:
        # readline has a weird interface to the completer.  We end up
        # recomputing the matches for each match, so it can take
        # O(n^2) time overall.  We could cache but it's not worth the
        # bother.
        matches = list(readline_complete(string))
        if index < len(matches):
            return matches[index]
        else:
            return None
    except:
        # The readline wrapper swallows any exception so we need to
        # print it if it is to be reported.
        traceback.print_exc()


def init_readline():
    readline.parse_and_bind("tab: complete")
    readline.set_completer(readline_complete_wrapper)
    readline.set_completer_delims(string.whitespace)


simple_builtins = {"cd": chdir_builtin}


def wrap_sudo(as_root, user):
    def sudo(args, pgroup, fds):
        return as_root.spawn(args, pgroup, fds)
    return {"sudo": sudo}, PrefixLauncher(["sudo", "-u", user], as_root)


class Shell(object):

    def __init__(self, output):
        self.job_controller = jobcontrol.JobController(
            jobcontrol.WaitDispatcher(), output)
        builtins = {}
        builtins.update(simple_builtins)
        builtins.update(self.job_controller.get_builtins())
        launcher = Launcher()
        if "SUDO_USER" in os.environ and os.getuid() == 0:
            sudo_builtins, launcher = wrap_sudo(
                launcher, os.environ["SUDO_USER"])
            builtins.update(sudo_builtins)
        self._launcher = LauncherWithBuiltins(launcher, builtins)

    def run_command(self, line, fds):
        run_command(self.job_controller, self._launcher, line, fds)


def get_prompt():
    try:
        cwd_path = unexpanduser(get_logical_cwd())
    except:
        cwd_path = "?"
    args = {"username": pwd.getpwuid(os.getuid()).pw_name,
            "hostname": socket.gethostname(),
            "cwd_path": cwd_path}
    format = u"%(username)s@%(hostname)s:%(cwd_path)s$$ "
    return (format % args).encode("utf-8")


class ReadlineReader(object):

    def readline(self, callback):
        try:
            line = raw_input(get_prompt())
        except EOFError:
            callback(None)
        else:
            callback(line)


def main():
    init_readline()
    shell = Shell(sys.stdout)
    fds = {FILENO_STDIN: sys.stdin,
           FILENO_STDOUT: sys.stdout,
           FILENO_STDERR: sys.stderr}
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    try:
        import shell_pyrepl
        reader = shell_pyrepl.make_reader(get_prompt, readline_complete)
        print "using pyrepl"
    except ImportError:
        reader = ReadlineReader()
        print "using readline (pyrepl not available)"
    should_run = [True]

    def read_input():
        shell.job_controller.shell_to_foreground()
        shell.job_controller.print_messages()
        reader.readline(process_input)

    def process_input(line):
        if line is None:
            sys.stdout.write("\n")
            should_run[0] = False
        else:
            try:
                shell.run_command(line, fds)
            except Exception:
                traceback.print_exc()
            read_input()

    read_input()
    while should_run[0]:
        gobject.main_context_default().iteration()


if __name__ == "__main__":
    main()
