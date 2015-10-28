#!/usr/bin/env python

"""
Note that this file is distributed under python license.


dummy client module for memcached

Made from the original python-memcache by Helge Tesdal, Plone Solutions AS

Overview
========

See U{the MemCached homepage<http://www.danga.com/memcached>} for more about memcached.

Usage summary
=============

This should give you a feel for how this module operates::

    import memcache
    mc = memcache.Client(['127.0.0.1:11211'], debug=0)

    mc.set("some_key", "Some value")
    value = mc.get("some_key")

    mc.set("another_key", 3)
    mc.delete("another_key")
    
    mc.set("key", "1")   # note that the key used for incr/decr must be a string.
    mc.incr("key")
    mc.decr("key")

The standard way to use memcache with a database is like this::

    key = derive_key(obj)
    obj = mc.get(key)
    if not obj:
        obj = backend_api.get(...)
        mc.set(obj)

    # we now have obj, and future passes through this code
    # will use the object from the cache.

Detailed Documentation
======================

More detailed documentation is available in the L{Client} class.
"""

import re
import sys
import time
import types
try:
    import cPickle as pickle
except ImportError:
    import pickle

__author__    = "Evan Martin <martine@danga.com>"
__version__ = "1.31"
__copyright__ = "Copyright (C) 2003 Danga Interactive"
__license__   = "Python"

invalid_key_pattern = re.compile(r"""[^A-Za-z0-9,./;'\\\[\]\-=`<>?:"{}|_+~!@#$%^&*()]""")

DATA = {} # Keyed on server list
EXPIRATION = {} # Keyed on server list

class _Error(Exception):
    pass

class Client(object):
    """
    Object representing a pool of memcache servers.
    
    See L{memcache} for an overview.

    The key has to be a string

    @group Setup: __init__, set_servers, forget_dead_hosts, disconnect_all, debuglog
    @group Insertion: set, add, replace
    @group Retrieval: get, get_multi
    @group Integers: incr, decr
    @group Removal: delete
    @sort: __init__, set_servers, forget_dead_hosts, disconnect_all, debuglog,\
           set, add, replace, get, get_multi, incr, decr, delete
    """
    dummyclient = True # Used for waiting in tests
    def __init__(self, servers, debug=0, pickleProtocol=0,
                 pickler=pickle.Pickler, unpickler=pickle.Unpickler,
                 pload=None, pid=None):
        """
        Create a new Client object with the given list of servers.

        @param servers: C{servers} is passed to L{set_servers}.
        @param debug: whether to display error messages when a server can't be
        contacted.
        """
        servers = tuple(servers)
        self.set_servers(servers)
        self.debug = debug
        self.stats = {}
        self._data = DATA.get(servers, {})
        DATA[servers] = self._data
        self._expiration = EXPIRATION.get(servers, {})
        EXPIRATION[servers] = self._expiration

        # Allow users to modify pickling/unpickling behavior
        self.pickleProtocol = pickleProtocol
        self.pickler = pickler
        self.unpickler = unpickler
        self.persistent_load = pload
        self.persistent_id = pid

    def _validate_key(self, key):
        if not isinstance(key, str):
            raise TypeError("argument 1 must be string, not %s" % type(key))
        if invalid_key_pattern.search(key):
            raise ValueError, 'invalid key: "%s"' % key


    def set_servers(self, servers):
        """
        Set the pool of servers used by this client.

        @param servers: an array of servers.
        Servers can be passed in two forms:
            1. Strings of the form C{"host:port"}, which implies a default weight of 1.
            2. Tuples of the form C{("host:port", weight)}, where C{weight} is
            an integer weight value.
        """
        self.servers = servers

    def get_stats(self):
        '''Get statistics from each of the servers.  

        @return: A list of tuples ( server_identifier, stats_dictionary ).
            The dictionary contains a number of name/value pairs specifying
            the name of the status field and the string value associated with
            it.  The values are not converted from strings.
        '''
        data = []
        for server in self.servers:
            data.append((server, {'curr_items':'%s'%len(self._data.keys()),
                                  'curr_connections':'1',
                                  'version':'testdummy',
                                  'total_items':'%s'%len(self._data.keys()),
                                  'bytes_read':1024,
                                  'bytes_written':256}))
        return data

    def flush_all(self):
        'Expire all data currently in the memcache servers.'
        self._data = {}
        self._expiration = {}

    def debuglog(self, str):
        if self.debug:
            sys.stderr.write("MemCached: %s\n" % str)

    def _statlog(self, func):
        if not self.stats.has_key(func):
            self.stats[func] = 1
        else:
            self.stats[func] += 1

    def forget_dead_hosts(self):
        """
        Reset every host in the pool to an "alive" state.
        """
        pass

    def disconnect_all(self):
        pass
    
    def delete(self, key, time=0):
        '''Deletes a key from the memcache.
        
        @return: Nonzero on success.
        @rtype: int
        '''
        self._validate_key(key)
        if not self.servers: return None
        self._statlog('delete')
        if self._data.has_key(key):
            del self._data[key]
            del self._expiration[key]
            return 1
        else:
            return 0

    def incr(self, key, delta=1):
        """
        Sends a command to the server to atomically increment the value for C{key} by
        C{delta}, or by 1 if C{delta} is unspecified.  Returns None if C{key} doesn't
        exist on server, otherwise it returns the new value after incrementing.

        Note that the value for C{key} must already exist in the memcache, and it
        must be the string representation of an integer.

        >>> mc.set("counter", "20")  # returns 1, indicating success
        1
        >>> mc.incr("counter")
        21
        >>> mc.incr("counter")
        22

        Overflow on server is not checked.  Be aware of values approaching
        2**32.  See L{decr}.

        @param delta: Integer amount to increment by (should be zero or greater).
        @return: New value after incrementing.
        @rtype: int
        """
        self._validate_key(key)
        if not self.servers: return None
        if self._data.has_key(key):
            try:
                number = int(self._data[key])
                number += delta
                self._data[key] = str(number)
                return number
            except ValueError:
                return None
        else:
            raise ValueError("Could not find %s" % key)

    def decr(self, key, delta=1):
        """
        Like L{incr}, but decrements.  Unlike L{incr}, underflow is checked and
        new values are capped at 0.  If server value is 1, a decrement of 2
        returns 0, not -1.

        @param delta: Integer amount to decrement by (should be zero or greater).
        @return: New value after decrementing.
        @rtype: int
        """
        self._validate_key(key)
        if not self.servers: return None
        if self._data.has_key(key):
            try:
                number = int(self._data[key])
                number = max(0, number - delta)
                self._data[key] = str(number)
                return number
            except ValueError:
                return None
        else:
            raise ValueError("Could not find %s" % key)

    def add(self, key, val, time=0):
        '''
        Add new key with value.
        
        Like L{set}, but only stores in memcache if the key doesn't already exist.

        @return: Nonzero on success.
        @rtype: int
        '''
        self._validate_key(key)
        if not self.servers: return None
        sanitycheck = pickle.dumps(val, self.pickleProtocol)
        if not self._data.has_key(key):
            self._data[key] = val
            self._expiration[key] = time
            return 1
        return 0

    def replace(self, key, val, time=0):
        '''Replace existing key with value.
        
        Like L{set}, but only stores in memcache if the key already exists.  
        The opposite of L{add}.

        @return: Nonzero on success.
        @rtype: int
        '''
        self._validate_key(key)
        if not self.servers: return None
        sanitycheck = pickle.dumps(val, self.pickleProtocol)
        if self._data.has_key(key):
            self._data[key] = val
            self._expiration[key] = time
            return 1
        return 0

    def set(self, key, val, max_age=0):
        '''Unconditionally sets a key to a given value in the memcache.

        The C{key} can optionally be an tuple, with the first element being the
        hash value, if you want to avoid making this module calculate a hash value.
        You may prefer, for example, to keep all of a given user's objects on the
        same memcache server, so you could use the user's unique id as the hash
        value.

        @return: Nonzero on success.
        @rtype: int
        '''
        self._validate_key(key)
        if not self.servers: return None
        sanitycheck = pickle.dumps(val, self.pickleProtocol)
        self._data[key] = val
        if max_age != 0:
            max_age = time.time() + max_age
        self._expiration[key] = max_age
        return 1

    def get(self, key):
        '''Retrieves a key from the memcache.
        
        @return: The value or None.
        '''
        self._validate_key(key)
        if not self.servers: return None
        self._statlog('get')
        value = self._data.get(key, None)
        if value is not None:
            expiry = self._expiration[key]
            if expiry > 0 and expiry < time.time():
                value = None
                del self._data[key]
                del self._expiration[key]
        return value

    def get_multi(self, keys):
        '''
        Retrieves multiple keys from the memcache doing just one query.
        
        >>> success = mc.set("foo", "bar")
        >>> success = mc.set("baz", 42)
        >>> mc.get_multi(["foo", "baz", "foobar"]) == {"foo": "bar", "baz": 42}
        1

        This method is recommended over regular L{get} as it lowers the number of
        total packets flying around your network, reducing total latency, since
        your app doesn't have to wait for each round-trip of L{get} before sending
        the next one.

        @param keys: An array of keys.
        @return:  A dictionary of key/value pairs that were available.

        '''

        self._statlog('get_multi')

        if not self.servers: return None
        result = {}
        for key in keys:
            self._validate_key(key)
            value = self.get(key)
            if value is not None:
                result[key] = value
        return result


def _doctest():
    import doctest, memcache
    servers = ["127.0.0.1:11211"]
    mc = Client(servers, debug=1)
    globs = {"mc": mc}
    return doctest.testmod(memcache, globs=globs)

if __name__ == "__main__":
    print "Testing docstrings..."
    _doctest()
    print "Running tests:"
    print
    #servers = ["127.0.0.1:11211", "127.0.0.1:11212"]
    servers = ["127.0.0.1:11211"]
    mc = Client(servers, debug=1)

    def to_s(val):
        if not isinstance(val, types.StringTypes):
            return "%s (%s)" % (val, type(val))
        return "%s" % val
    def test_setget(key, val):
        print "Testing set/get {'%s': %s} ..." % (to_s(key), to_s(val)),
        mc.set(key, val)
        newval = mc.get(key)
        if newval == val:
            print "OK"
            return 1
        else:
            print "FAIL"
            return 0

    class FooStruct:
        def __init__(self):
            self.bar = "baz"
        def __str__(self):
            return "A FooStruct"
        def __eq__(self, other):
            if isinstance(other, FooStruct):
                return self.bar == other.bar
            return 0
        
    test_setget("a_string", "some random string")
    test_setget("an_integer", 42)
    if test_setget("long", long(1<<30)):
        print "Testing delete ...",
        if mc.delete("long"):
            print "OK"
        else:
            print "FAIL"
    print "Testing get_multi ...",
    print mc.get_multi(["a_string", "an_integer"])

    print "Testing get(unknown value) ...",
    print to_s(mc.get("unknown_value"))

    f = FooStruct()
    test_setget("foostruct", f)

    print "Testing incr ...",
    x = mc.incr("an_integer", 1)
    if x == 43:
        print "OK"
    else:
        print "FAIL"

    print "Testing decr ...",
    x = mc.decr("an_integer", 1)
    if x == 42:
        print "OK"
    else:
        print "FAIL"



# vim: ts=4 sw=4 et :
