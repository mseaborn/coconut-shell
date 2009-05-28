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
import functools
import gc
import glob
import grp
import itertools
import os
import pwd
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

    def eval(self, spec):
        spec["args"].append(self._string)


class ExpandStringArgument(object):

    def __init__(self, string):
        self._string = string
        # TODO: should check for "[" and "]" as well
        # This is an optimisation.  If this is not a glob expression,
        # checking the filesystem would be pointless.
        self._do_glob = "*" in string or "?" in string

    def eval(self, spec):
        string = os.path.expanduser(self._string)
        if self._do_glob:
            matches = sorted(spec["cwd"].relative_op(lambda: glob.glob(string)))
            if len(matches) > 0:
                spec["args"].extend(matches)
                return
        spec["args"].append(string)


class RedirectFD(object):

    def __init__(self, fd1, fd2):
        self._fd1 = fd1
        self._fd2 = fd2

    def eval(self, spec):
        spec["fds"][self._fd1] = spec["fds"][self._fd2]


class RedirectFile(object):

    def __init__(self, dest_fd, mode, filename):
        self._dest_fd = dest_fd
        self._mode = mode
        self._filename = filename

    def eval(self, spec):
        spec["fds"][self._dest_fd] = \
            spec["cwd"].relative_op(lambda: open(self._filename, self._mode))


def copy_spec(spec):
    spec = spec.copy()
    spec["fds"] = spec["fds"].copy()
    return spec


class CommandExp(object):

    def __init__(self, args):
        self._args = args

    def run(self, launcher, job, spec):
        spec = copy_spec(spec)
        spec["args"] = []
        for arg in self._args:
            arg.eval(spec)
        launcher.spawn(job, spec)


class PipelineExp(object):

    def __init__(self, cmd1, cmd2):
        self._cmd1 = cmd1
        self._cmd2 = cmd2

    def run(self, launcher, job, spec):
        pipe_read_fd, pipe_write_fd = os.pipe()
        spec1 = copy_spec(spec)
        spec2 = copy_spec(spec)
        spec1["fds"][FILENO_STDOUT] = os.fdopen(pipe_write_fd, "w")
        spec2["fds"][FILENO_STDIN] = os.fdopen(pipe_read_fd, "r")
        self._cmd1.run(launcher, job, spec1)
        self._cmd2.run(launcher, job, spec2)


class JobExp(object):

    def __init__(self, cmd, is_foreground, cmd_text):
        self._cmd = cmd
        self._is_foreground = is_foreground
        self._cmd_text = cmd_text

    def run(self, job_spawner, launcher, spec):
        job_procs = []
        self._cmd.run(launcher, job_procs, spec)
        if len(job_procs) > 0:
            job_spawner.start_job(job_procs, self._is_foreground,
                                  self._cmd_text)


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


class Launcher(object):

    def spawn(self, job_procs, spec):
        job_procs.append(spec)


class SudoLauncher(object):

    def __init__(self, user, launcher):
        self._launcher = launcher
        self._user = user

    def spawn(self, job, spec):
        spec = copy_spec(spec)
        entry = pwd.getpwnam(self._user)
        spec["uid"] = entry.pw_uid
        spec["gid"] = entry.pw_gid
        spec["groups"] = [entry.pw_gid]
        spec["groups"].extend([group.gr_gid for group in grp.getgrall()
                               if self._user in group.gr_mem])
        self._launcher.spawn(job, spec)


def make_chdir_builtin(cwd_tracker, environ):
    def chdir_builtin(job, spec):
        args = spec["args"]
        if len(args) == 0:
            # TODO: report nicer error when HOME is not set
            cwd_tracker.chdir(environ["HOME"])
        else:
            for arg in args:
                cwd_tracker.chdir(arg)
    return chdir_builtin


class LauncherWithBuiltins(object):

    def __init__(self, launcher, builtins):
        self._launcher = launcher
        self._builtins = builtins

    def spawn(self, job, spec):
        builtin = self._builtins.get(spec["args"][0])
        if builtin is not None:
            spec = copy_spec(spec)
            spec["args"] = spec["args"][1:]
            return builtin(job, spec)
        else:
            return self._launcher.spawn(job, spec)


def get_one(lst):
    assert len(lst) == 1, lst
    return lst[0]


def run_command(job_spawner, launcher, line, spec):
    top_expr = top_command + parse.StringEnd()
    for cmd in top_expr.parseString(line):
        cmd.run(job_spawner, launcher, spec)


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


# Can't use os.fdopen() to wrap directory FDs, because it fstat()s the
# FD and rejects directory FDs.
class FDWrapper(object):

    def __init__(self, fd):
        assert isinstance(fd, int)
        self._fd = fd

    def __del__(self):
        os.close(self._fd)

    def fileno(self):
        return self._fd


# gnome-terminal uses a process's cwd when opening new tabs/windows,
# so it's still useful to set the process-global cwd.
class GlobalCwdTracker(object):

    def get_cwd_fd(self):
        return FDWrapper(os.open(".", os.O_RDONLY))

    def relative_op(self, func):
        return func()

    def get_cwd(self):
        return os.getcwd()

    def chdir(self, dir_path):
        os.chdir(dir_path)

    def get_stat(self):
        return os.stat(".")


class LocalCwdTracker(object):

    def __init__(self, cwd_fd=None):
        if cwd_fd is None:
            cwd_fd = FDWrapper(os.open(".", os.O_RDONLY))
        self._cwd_fd = cwd_fd

    def get_cwd_fd(self):
        return self._cwd_fd

    def relative_op(self, func):
        # Not thread-safe.  Would be better to use *at() syscalls, but
        # they are not readily available from Python, and not all
        # calls have a *at() equivalent.  For example, there is no
        # fgetcwd().
        old_cwd = FDWrapper(os.open(".", os.O_RDONLY))
        try:
            os.fchdir(self._cwd_fd)
            return func()
        finally:
            os.fchdir(old_cwd)

    def get_cwd(self):
        return self.relative_op(os.getcwd)

    def chdir(self, dir_path):
        self._cwd_fd = self.relative_op(
            lambda: FDWrapper(os.open(dir_path, os.O_RDONLY | os.O_DIRECTORY)))

    def get_stat(self):
        return os.fstat(self._cwd_fd.fileno())

    def copy(self):
        return LocalCwdTracker(self.get_cwd_fd())


class LogicalCwd(object):

    def __init__(self, cwd_tracker, environ):
        self._cwd_tracker = cwd_tracker
        self._environ = environ

    # Bash uses PWD to remember the cwd pathname before symlink expansion.
    def chdir(self, path):
        if os.path.isabs(path):
            new_cwd = path
        else:
            new_cwd = os.path.join(self.get_cwd(), path)
        # Note that ".." is applied after symlink expansion.  We don't
        # attempt to follow Bash's behaviour here.
        self._cwd_tracker.chdir(path)
        # Only set this if chdir() succeeds.
        self._environ["PWD"] = os.path.normpath(new_cwd)

    def get_cwd(self):
        path = self._environ.get("PWD")
        if path is not None:
            try:
                stat1 = os.stat(path)
                stat2 = self._cwd_tracker.get_stat()
            except OSError:
                pass
            else:
                if (stat1.st_dev == stat2.st_dev and
                    stat1.st_ino == stat2.st_ino):
                    return path
        return self._cwd_tracker.get_cwd()


def remove_prefix(prefix, string):
    assert string.startswith(prefix), (prefix, string)
    return string[len(prefix):]


def complete_prefix_filename(filename):
    # We don't use glob for this because glob will collapse multiple
    # trailing slashes.  e.g. glob("foo//*") -> ["foo/bar"].
    # Also, we don't want stars in the filename to be interpreted by glob.
    if "/" in filename:
        index = filename.rindex("/") + 1
        dir_name = filename[:index]
        leaf_prefix = filename[index:]
        leaves = os.listdir(dir_name)
    else:
        dir_name = ""
        leaf_prefix = filename
        leaves = os.listdir(".")
    for leaf in leaves:
        if leaf.startswith(leaf_prefix):
            yield dir_name + leaf


def complete_path_command(path, prefix):
    for dir_path in path.split(":"):
        for filename in complete_prefix_filename("%s/%s" % (dir_path, prefix)):
            try:
                st = os.stat(filename)
            except OSError:
                pass
            else:
                if st.st_mode & 0111 != 0:
                    yield remove_prefix(dir_path + "/", filename)


def complete_filename(string):
    filename, reverse_expansion = expanduser(string)
    for filename in complete_prefix_filename(filename):
        if os.path.isdir(filename):
            # This treats symlinks to directories differently from Bash,
            # but this might be considered an improvement.
            yield reverse_expansion(filename) + "/"
        else:
            yield reverse_expansion(filename)


def readline_complete(cwd, environ, context, string):
    def func():
        names = set()
        if context.strip() == "":
            names.update(complete_path_command(environ.get("PATH", ""), string))
        names.update(complete_filename(string))
        return sorted(names)
    return cwd.relative_op(func)


def wrap_sudo(as_root, user):
    def sudo(job, spec):
        return as_root.spawn(job, spec)
    return {"sudo": sudo}, SudoLauncher(user, as_root)


def make_get_prompt(cwd_tracker):
    def get_prompt():
        try:
            cwd_path = unexpanduser(cwd_tracker.get_cwd())
        except:
            cwd_path = "?"
        args = {"username": pwd.getpwuid(os.getuid()).pw_name,
                "hostname": socket.gethostname(),
                "cwd_path": cwd_path}
        format = u"%(username)s@%(hostname)s:%(cwd_path)s$$ "
        return (format % args).encode("utf-8")
    return get_prompt


def make_shell(parts):
    parts.setdefault("job_output", sys.stdout)
    parts.setdefault("job_tty", sys.stdout)
    parts.setdefault("wait_dispatcher", jobcontrol.WaitDispatcher())
    parts.setdefault("job_controller", jobcontrol.JobController(
        parts["wait_dispatcher"], parts["job_output"], parts["job_tty"]))
    parts.setdefault("job_spawner", jobcontrol.ProcessGroupJobSpawner(
            parts["wait_dispatcher"], parts["job_controller"],
            parts["job_tty"]))
    parts.setdefault("environ", os.environ)
    parts.setdefault("real_cwd", GlobalCwdTracker())
    parts.setdefault("cwd", LogicalCwd(parts["real_cwd"], parts["environ"]))
    parts.setdefault("get_prompt", make_get_prompt(parts["cwd"]))
    parts.setdefault("completer", functools.partial(
            readline_complete, parts["real_cwd"], parts["environ"]))
    parts.setdefault("builtins", {})
    parts["builtins"]["cd"] = make_chdir_builtin(parts["cwd"], parts["environ"])
    parts["builtins"].update(parts["job_controller"].get_builtins())
    launcher = Launcher()
    if "SUDO_USER" in os.environ and os.getuid() == 0:
        sudo_builtins, launcher = wrap_sudo(
            launcher, os.environ["SUDO_USER"])
        parts["builtins"].update(sudo_builtins)
    parts.setdefault("launcher", LauncherWithBuiltins(launcher,
                                                      parts["builtins"]))


class Shell(object):

    def __init__(self, parts):
        self._parts = parts
        make_shell(parts)
        self.__dict__.update(parts)

    def _make_spec(self, fds):
        return {"fds": fds,
                "environ": self.environ,
                "cwd_fd": self.real_cwd.get_cwd_fd(),
                "cwd": self.real_cwd}

    def run_command(self, line, fds):
        run_command(self.job_spawner, self.launcher, line, self._make_spec(fds))

    def run_job_command(self, line, fds, job_spawner):
        run_command(job_spawner, self.launcher, line, self._make_spec(fds))


class ReadlineReader(object):

    def __init__(self, get_prompt, completer):
        self._get_prompt = get_prompt
        self._completer = completer
        # Don't import readline until we actually need it, because it
        # has the side effect of setting the environment variables
        # LINES and COLUMNS.  When these are set wrongly (with the
        # enclosing tty's size) it messes up the output of some
        # console programs such as "top".
        import readline
        readline.parse_and_bind("tab: complete")
        readline.set_completer(self._readline_complete_wrapper)
        readline.set_completer_delims(string.whitespace)

    def readline(self, callback):
        try:
            line = raw_input(self._get_prompt())
        except EOFError:
            callback(None)
        else:
            callback(line)

    def _readline_complete_wrapper(self, string, index):
        try:
            # readline has a weird interface to the completer.  We end up
            # recomputing the matches for each match, so it can take
            # O(n^2) time overall.  We could cache but it's not worth the
            # bother.
            context = readline.get_line_buffer()[:readline.get_begidx()]
            matches = list(self._completer(context, string))
            if index < len(matches):
                return matches[index]
            else:
                return None
        except:
            # The readline wrapper swallows any exception so we need to
            # print it if it is to be reported.
            traceback.print_exc()


def main():
    shell = Shell({})
    fds = {FILENO_STDIN: sys.stdin,
           FILENO_STDOUT: sys.stdout,
           FILENO_STDERR: sys.stderr}
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    try:
        import shell_pyrepl
        reader = shell_pyrepl.make_reader(shell.get_prompt, shell.completer)
        print "using pyrepl"
    except ImportError:
        reader = ReadlineReader(shell.get_prompt, shell.completer)
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
