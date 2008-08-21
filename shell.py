#!/usr/bin/env python

import glob
import os
import readline
import subprocess
import string
import sys
import traceback

import pyparsing as parse


class CommandExp(object):

    def __init__(self, args):
        self._args = args

    def run(self, stdin, stdout):
        return [subprocess.Popen(self._args, stdin=stdin, stdout=stdout,
                                 close_fds=True)]


class PipelineExp(object):

    def __init__(self, cmd1, cmd2):
        self._cmd1 = cmd1
        self._cmd2 = cmd2

    def run(self, stdin, stdout):
        pipe_read_fd, pipe_write_fd = os.pipe()
        pipe_read = os.fdopen(pipe_read_fd, "r")
        pipe_write = os.fdopen(pipe_write_fd, "w")
        procs = []
        procs.extend(self._cmd1.run(stdin=stdin, stdout=pipe_write))
        procs.extend(self._cmd2.run(stdin=pipe_read, stdout=stdout))
        return procs


# TODO: doesn't handle backslash right
double_quoted = parse.QuotedString(quoteChar='"', escChar='\\', multiline=True)
single_quoted = parse.QuotedString(quoteChar="'", escChar='\\', multiline=True)

special_chars = "|\"'"
bare_chars = "".join(sorted(set(parse.srange("[a-zA-Z0-9]") +
                                string.punctuation)
                            - set(special_chars)))

argument = parse.Word(bare_chars) | double_quoted | single_quoted

command = (argument + parse.ZeroOrMore(argument)) \
          .setParseAction(lambda text, loc, args: CommandExp(args))

pipeline = parse.delimitedList(command, delim='|') \
           .setParseAction(lambda text, loc, cmds: reduce(PipelineExp, cmds))


def get_one(lst):
    assert len(lst) == 1, lst
    return lst[0]


def run_command(line, stdin, stdout):
    top_expr = pipeline + parse.StringEnd()
    cmd = get_one(top_expr.parseString(line))
    procs = cmd.run(stdin, stdout)
    for proc in procs:
        proc.wait()


def readline_complete(string):
    for filename in sorted(glob.glob(string + "*")):
        if os.path.isdir(filename):
            # This treats symlinks to directories differently from Bash,
            # but this might be considered an improvement.
            yield filename + "/"
        else:
            yield filename


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
            run_command(line, stdin=sys.stdin, stdout=sys.stdout)
        except Exception:
            traceback.print_exc()


if __name__ == "__main__":
    main()
