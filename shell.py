
import glob
import os
import readline
import subprocess
import string
import sys
import traceback

import pyparsing as parse


# TODO: doesn't handle backslash right
quoted = parse.QuotedString(quoteChar='"', escChar='\\', multiline=True)

special_chars = "\"'"
bare_chars = "".join(sorted(set(parse.srange("[a-zA-Z0-9]") +
                                string.punctuation)
                            - set(special_chars)))

argument = parse.Word(bare_chars) | quoted

command = argument + parse.ZeroOrMore(argument) + parse.StringEnd()


def run_command(line, stdout):
    cmd = command.parseString(line)
    subprocess.call(cmd, stdout=stdout)


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
            run_command(line, stdout=sys.stdout)
        except Exception:
            traceback.print_exc()


if __name__ == "__main__":
    main()
