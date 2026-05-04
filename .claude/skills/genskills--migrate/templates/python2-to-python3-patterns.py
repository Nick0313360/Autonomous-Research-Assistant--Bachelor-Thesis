# Print statement → function
print "hello"        # Py2
print("hello")       # Py3

# Integer division
5 / 2  # = 2 in Py2, = 2.5 in Py3
5 // 2 # = 2 in both (use this for integer division)

# Unicode
u"string"            # Py2 unicode
"string"             # Py3 (all strings are unicode)
b"bytes"             # Py3 bytes literal

# Dictionary methods
d.keys()             # Py2: returns list. Py3: returns view
list(d.keys())       # Works in both

# range vs xrange
xrange(10)           # Py2 (lazy)
range(10)            # Py3 (lazy, xrange removed)

# Imports renamed
import ConfigParser   # Py2
import configparser   # Py3

import Queue          # Py2
import queue          # Py3

# Exception syntax
except Exception, e:  # Py2
except Exception as e: # Py3

# Metaclasses
__metaclass__ = Meta  # Py2
class Foo(metaclass=Meta): # Py3
