

# This came from here:
# http://www.gossamer-threads.com/lists/python/python/769679#769679
# Thank you jch. 


import re


def expand_braces(string):
    pos = string.find('{')
    # simple, single element string
    if pos < 0:
            return [string]
    # find the left, middle comma-separated string and the right
    left = string[:pos]
    middle = []
    count = 1
    for i in range(pos+1, len(string)):
        if count == 1 and string[i] == ',':
            middle.append(string[pos+1:i])
            pos = i
        elif count == 1 and string[i] == '}':
            middle.append(string[pos+1:i])
            pos = i
            break
        elif string[i] == '{':
            count += 1
        elif string[i] == '}':
            count -= 1
    right = string[pos+1:]
    # just "{x..y}" is a special case
    if len(middle) == 1:
        r = re.match("^(-?\d+)\.\.(-?\d+)$", middle[0])
        if not r:
            r = re.match("^(.)\.\.(.)$", middle[0])
    else:
        r = None
    if r:
        middle = []
        start = r.group(1)
        end = r.group(2)
        if len(start) != 1 or len(end) != 1:
            mapper = str
            start = int(start)
            end = int(end)
        else:
            mapper = chr
            start = ord(start)
            end = ord(end)
        if start <= end:
            middle = map(mapper, range(start, end+1))
        else:
            middle = map(mapper, range(start, end-1, -1))
    # join all the bits together
    result = []
    right = expand_braces(right)
    for m in middle:
        for m1 in expand_braces(m):
            for r in right:
                result.append("".join((left, m1, r)))
    return result
