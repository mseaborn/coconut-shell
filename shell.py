
import subprocess
import traceback
import string
import sys

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
