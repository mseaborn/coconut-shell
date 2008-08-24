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

import glob
import os
import pwd
import readline
import signal
import subprocess
import string
import sys
import traceback

import pyparsing as parse


def set_up_signals():
    # Python changes signal handler settings on startup, including
    # setting SIGPIPE to SIG_IGN (ignore), which gets inherited by
    # child processes.  I am surprised this does not cause problems
    # more often.  Change the setting back.
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)


class StringArgument(object):

    def __init__(self, string):
        self._string = string

    def eval(self):
        return [self._string]


class ExpandStringArgument(object):

    def __init__(self, string):
        self._string = string
        # TODO: should check for "[" and "]" as well
        # This is an optimisation.  If this is not a glob expression,
        # checking the filesystem would be pointless.
        self._do_glob = "*" in string or "?" in string

    def eval(self):
        string = os.path.expanduser(self._string)
        if self._do_glob:
            matches = sorted(glob.glob(string))
            if len(matches) > 0:
                return matches
        return [string]


class CommandExp(object):

    def __init__(self, args):
        self._args = args

    def run(self, stdin, stdout, stderr):
        evaled_args = []
        for arg in self._args:
            evaled_args.extend(arg.eval())
        if evaled_args[0] == "cd":
            chdir_args = evaled_args[1:]
            if len(chdir_args) == 0:
                # TODO: report nicer error when HOME is not set
                os.chdir(os.environ["HOME"])
            else:
                for arg in chdir_args:
                    os.chdir(arg)
            return []
        else:
            proc = subprocess.Popen(
                evaled_args, stdin=stdin, stdout=stdout,
                stderr=stderr, close_fds=True, preexec_fn=set_up_signals)
            return [proc]


class PipelineExp(object):

    def __init__(self, cmd1, cmd2):
        self._cmd1 = cmd1
        self._cmd2 = cmd2

    def run(self, stdin, stdout, stderr):
        pipe_read_fd, pipe_write_fd = os.pipe()
        pipe_read = os.fdopen(pipe_read_fd, "r")
        pipe_write = os.fdopen(pipe_write_fd, "w")
        procs = []
        procs.extend(self._cmd1.run(stdin=stdin, stdout=pipe_write,
                                    stderr=stderr))
        procs.extend(self._cmd2.run(stdin=pipe_read, stdout=stdout,
                                    stderr=stderr))
        return procs


# TODO: doesn't handle backslash right
double_quoted = parse.QuotedString(quoteChar='"', escChar='\\', multiline=True)
single_quoted = parse.QuotedString(quoteChar="'", escChar='\\', multiline=True)
quoted_argument = (double_quoted | single_quoted) \
    .setParseAction(lambda text, loc, arg: StringArgument(get_one(arg)))

special_chars = "|\"'"
bare_chars = "".join(sorted(set(parse.srange("[a-zA-Z0-9]") +
                                string.punctuation)
                            - set(special_chars)))
bare_argument = parse.Word(bare_chars) \
    .setParseAction(lambda text, loc, arg: ExpandStringArgument(get_one(arg)))

argument = bare_argument | quoted_argument

command = (argument + parse.ZeroOrMore(argument)) \
          .setParseAction(lambda text, loc, args: CommandExp(args))

pipeline = parse.delimitedList(command, delim='|') \
           .setParseAction(lambda text, loc, cmds: reduce(PipelineExp, cmds))

top_command = parse.Optional(pipeline)


def get_one(lst):
    assert len(lst) == 1, lst
    return lst[0]


def run_command(line, stdin, stdout, stderr):
    top_expr = top_command + parse.StringEnd()
    for cmd in top_expr.parseString(line):
        procs = cmd.run(stdin, stdout, stderr)
        for proc in procs:
            proc.wait()


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


def main():
    init_readline()
    while True:
        prompt = "$ "
        try:
            line = raw_input(prompt)
        except EOFError:
            sys.stdout.write("\n")
            break
        try:
            run_command(line, stdin=sys.stdin, stdout=sys.stdout,
                        stderr=sys.stderr)
        except Exception:
            traceback.print_exc()


if __name__ == "__main__":
    main()
