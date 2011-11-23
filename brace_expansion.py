
# Copyright (C) 2011 Andrew Hamilton
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

import string

import pyparsing as parse


class Word(object):

    def __init__(self, word):
        self.word = word

    def __iter__(self):
        yield self.word

    def __str__(self):
        return self.word


class IntegerRange(object):

    def __init__(self, args):
        self.start, elipsis, self.end = args

    def __iter__(self):
        if self.end > self.start:
            return (str(num) for num in 
                    range(int(self.start), int(self.end) + 1))
        else:
            return (str(num) for num in 
                    range(int(self.start), int(self.end) - 1, -1))


class CharacterRange(object):

    def __init__(self, args):
        self.start, elipsis, self.end = args

    def __iter__(self):
        if self.end > self.start:
            return (chr(code) for code in 
                    range(ord(self.start), ord(self.end) + 1))
        else:
            return (chr(code) for code in 
                    range(ord(self.start), ord(self.end) - 1, -1))


class MiddlePart(object):

    def __init__(self, args):
        self.args = args

    def __iter__(self):
        if len(self.args) == 1:
            yield ""
        else:
            for part in self.args[1]:
                yield part


class Middle(object):

    def __init__(self, args):
        self.args = args

    def __iter__(self):
        for arg in self.args:
            for part in arg:
                yield part


class Brace(object):

    def __init__(self, args):
        self.args = args

    def __iter__(self):
        right = [""] if self.args.right == "" else self.args.right 
        for middle_part in self.args.middle:
            for right_part in right:
                yield str(self.args.left) + middle_part + right_part


special_chars = "|&\"'<>{},"

bare_chars = "".join(sorted(set(parse.srange("[a-zA-Z0-9]") +
                                string.punctuation)
                            - set(special_chars)))

word = (parse.Word(bare_chars) | parse.QuotedString(quoteChar='"')) \
    .setParseAction(lambda text, loc, args: Word(args[0]))

integer = (parse.Optional("-") + parse.Word(parse.nums)) \
    .setParseAction(lambda text, loc, args: int("".join(args)))

integer_range = (integer + ".." + integer) \
    .setParseAction(lambda text, loc, args: IntegerRange(args))

character_range = (
    parse.Word(parse.alphas, max=1) + ".." + parse.Word(parse.alphas, max=1)) \
    .setParseAction(lambda text, loc, args: CharacterRange(args))

range_ = integer_range | character_range

brace = parse.Forward()

middle_part = (
    "," + parse.Optional(brace | word).setResultsName("brace")) \
    .setParseAction(lambda text, loc, args: MiddlePart(args))

middle = (
    parse.Literal("{").suppress() + 
    (range_ | ((brace | word) + parse.ZeroOrMore(middle_part))) + 
    parse.Literal("}").suppress()) \
    .setParseAction(lambda text, loc, args: Middle(args))

brace << (
    parse.Optional(word).setResultsName("left") + 
    middle.setResultsName("middle") + 
    parse.Optional(brace | word).setResultsName("right")) \
    .setParseAction(lambda text, loc, args: Brace(args)).leaveWhitespace()


def expand_braces(brace_expression):
    return brace.parseString(brace_expression)[0]
