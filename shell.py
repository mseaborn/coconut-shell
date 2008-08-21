
import subprocess
import traceback
import sys

import pyparsing as parse


# TODO: doesn't handle backslash right
quoted = parse.QuotedString(quoteChar='"', escChar='\\', multiline=True)

argument = parse.Word(parse.srange("[a-zA-Z0-9_]")) | quoted

command = argument + parse.ZeroOrMore(argument)


def run_command(line, stdout):
    cmd = command.parseString(line)
    subprocess.call(cmd, stdout=stdout)


def main():
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
