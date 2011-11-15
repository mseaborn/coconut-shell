

# These tests came from here:
# http://www.gossamer-threads.com/lists/python/python/769679#769679 


import unittest

import brace_expansion


class BraceExpansionTestCase(unittest.TestCase):

    def test_brace_expansion(self):
        def test(argument, expected):
            result = " ".join(brace_expansion.expand_braces(argument))
            self.assertEquals(result, expected)
        test('hello', 'hello')
        test('{hello,world}', 'hello world')
        test('x{a,b}', 'xa xb')
        test('x{a,b,c}y', 'xay xby xcy')
        test('A{1,2,3}B-C{4,5,6}D', 'A1B-C4D A1B-C5D A1B-C6D A2B-C4D A2B-C5D '
             'A2B-C6D A3B-C4D A3B-C5D A3B-C6D')
        test('a{b,<{c,d}>}e', 'abe a<c>e a<d>e')
        test('{1..10x}', '1..10x')
        test('{x1..10}', 'x1..10')
        test('{1..10}', '1 2 3 4 5 6 7 8 9 10')
        test('a{1..10}b', 'a1b a2b a3b a4b a5b a6b a7b a8b a9b a10b')
        test('{a,b}1..10', 'a1..10 b1..10')
        test('{a,9..13,b}', 'a 9..13 b')
        test('<{a,{9..13},b}>', '<a> <9> <10> <11> <12> <13> <b>')
        test('electron_{n,{pt,eta,phi}[{1,2}]}', 'electron_n electron_pt[1] '
             'electron_pt[2] electron_eta[1] electron_eta[2] electron_phi[1] '
             'electron_phi[2]')
        test('Myfile{1,3..10}.root', 'Myfile1.root Myfile3..10.root')
        test('Myfile{1,{3..10}}.root', 
             'Myfile1.root Myfile3.root Myfile4.root Myfile5.root '
             'Myfile6.root Myfile7.root Myfile8.root Myfile9.root '
             'Myfile10.root')
        test('{pre,,post}amble', 'preamble amble postamble')
        test('amble{a,b,}}', 'amblea} ambleb} amble}')
        test('{1..10}', '1 2 3 4 5 6 7 8 9 10')
        test('{a..j}', 'a b c d e f g h i j')
        test('{10..1}', '10 9 8 7 6 5 4 3 2 1')
        test('{j..a}', 'j i h g f e d c b a')
        test('{10..-10}', '10 9 8 7 6 5 4 3 2 1 0 -1 -2 -3 -4 -5 -6 -7 -8 -9 '
             '-10')


if __name__ == "__main__":
    unittest.main()
