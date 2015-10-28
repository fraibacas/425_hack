##############################################################################
#
# Copyright (c) 2005 Zope Corporation and Contributors. All Rights Reserved.
#
# This software is subject to the provisions of the Zope Public License,
# Version 2.0 (ZPL).  A copy of the ZPL should accompany this distribution.
# THIS SOFTWARE IS PROVIDED "AS IS" AND ANY AND ALL EXPRESS OR IMPLIED
# WARRANTIES ARE DISCLAIMED, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF TITLE, MERCHANTABILITY, AGAINST INFRINGEMENT, AND FITNESS
# FOR A PARTICULAR PURPOSE
#
##############################################################################
"""
memcached manager --
  Caches the results of method calls in memcached.

$Id: MemcachedManager.py 145960 2010-10-11 09:15:18Z tesdal $
"""

import re
import time
import logging
import md5

try:
    import pylibmc as memcache
except ImportError:
    import memcache

from itertools import chain
from thread import get_ident
from Acquisition import aq_base
from Acquisition import aq_get
from OFS.Cache import Cache, CacheManager
from OFS.SimpleItem import SimpleItem
from Globals import DTMLFile, InitializeClass

_marker = []  # Create a new marker object.

logger = logging.getLogger('MemcachedManager')

invalid_key_pattern = re.compile(r"""[^A-Za-z0-9,./;'\\\[\]\-=`<>?:"{}|_+~!@#$%^&*()]""")
if memcache.__name__ != 'pylibmc':
    class Client(memcache.Client):

        def debuglog(self, msg):
            if getattr(self, 'debug', False):
                logger.log(logging.DEBUG, msg)

else:
    from _pylibmc import MemcachedError
    class Client(object):

        behaviors = {
            "tcp_nodelay": True,
            "ketama": True,
            "cache_lookups": True
            }

        def __init__(self, servers, debug=False, pickleProtocol=None):
            # pickle protocol is always set to -1 in pylibmc
            self.debug = debug
            self._client = memcache.Client(servers, binary=True)
            self._client.set_behaviors(self.behaviors)
            if memcache.support_compression:
                self.min_compress_len = 1000
            else:
                self.min_compress_len = 0

        def debuglog(self, msg):
            if getattr(self, 'debug', False):
                logger.log(logging.DEBUG, msg)

        def get(self, key):
            try:
                return self._client.get(key)
            except MemcachedError, e:
                self.debuglog('memcached.get failed %s' % e)
                return None

        def set(self, key, value, time=0):
            try:
                return self._client.set(
                    key, value, time=time, min_compress_len=self.min_compress_len)
            except MemcachedError, e:
                self.debuglog('memcached.set failed %s' % e)
                return None

        def delete(self, key):
            try:
                return self._client.delete(key)
            except MemcachedError, e:
                self.debuglog('memcached.delete failed %s' % e)
                return None

        def incr(self, key):
            try:
                return self._client.incr(key)
            except MemcachedError, e:
                self.debuglog('memcached.incr failed %s' % e)
                return None

        def flush_all(self):
            try:
                self._client.flush_all()
            except MemcachedError, e:
                self.debuglog('memcached.flush_all failed %s' % e)
                return None

        def disconnect_all(self):
            try:
                self._client.disconnect_all()
            except MemcachedError, e:
                self.debuglog('memcached.disconnect_all failed %s' % e)
                return None

        def get_stats(self):
            try:
                return self._client.get_stats()
            except MemcachedError, e:
                self.debuglog('memcached.get_stats failed %s' % e)
                return None


class ObjectCacheEntries(dict):
    """Represents the cache for one Zope object.
    """

    def __init__(self, h):
        self.h = h.strip().rstrip('/')

    def aggregateIndex(self, view_name, req, req_names, local_keys, cachecounter):
        """Returns the index to be used when looking for or inserting
        a cache entry.
        view_name is a string.
        local_keys is a mapping or None.
        """
        req_index = []
        # Note: req_names is already sorted.
        for key in req_names:
            if req is None:
                val = ''
            else:
                val = req.get(key, '')
            req_index.append((str(key), str(val)))
        local_index = []
        if local_keys:
            for key, val in local_keys.items():
                local_index.append((str(key), str(val)))
            local_index.sort()
        
        md5obj = md5.new(self.h)
        md5obj.update(str(view_name))
        for key, val in chain(req_index, local_index):
            md5obj.update(key)
            md5obj.update(val)
        md5obj.update(cachecounter) # Updated on invalidation

        return md5obj.hexdigest()

    def getEntry(self, lastmod, cache, index):
        data = cache.get(index)

        if data is None:
            return _marker

        if not isinstance(data, tuple):
            logger.error('getEntry key %r under %r got %s, '
                         'expected metadata tuple', 
                         index, self.h, repr(data))
            return _marker

        if not len(data) == 2:
            logger.error('getEntry key %r under %r got %s, '
                         'expected metadata tuple of len() == 2', 
                         index, self.h, repr(data))
            return _marker

        if data[1] < lastmod:
            # Expired, remove from cache.
            cache.delete(index)
            return _marker

        return data[0]

    def setEntry(self, lastmod, cache, index, data, max_age=0):
        logger.debug('Storing %r under %r', index, self.h)
        cache.set(index, (data, lastmod), max_age)


class Memcached(Cache):
    # Note that objects of this class are not persistent,
    # nor do they make use of acquisition.

    cachecountervariable = '_memcachedcounter'

    def __init__(self):
        self.cache = None

    def initSettings(self, kw):
        # Note that we lazily allow MemcachedManager
        # to verify the correctness of the internal settings.
        self.__dict__.update(kw)
        servers = kw.get('servers', ('127.0.0.1:11211',))
        self.mirrors = kw.get('mirrors', ())
        debug = kw.get('debug', 1)
        if self.cache is not None:
            self.cache.disconnect_all()
        self.cache = Client(servers, debug=debug, pickleProtocol=-1)
        self.cache.debuglog(
            '(%s) initialized client '
            'with servers: %s' % (get_ident(), ', '.join(servers)))

    def getObjectCacheEntries(self, ob, create=0):
        """Finds or creates the associated ObjectCacheEntries object.
        """
        # Use URL to avoid hash conflicts
        # and enable different keys through different URLs
        h = getattr(ob, '_p_oid', None)
        if h is None:
            h = ob.absolute_url()
        return ObjectCacheEntries(h)

    def cleanup(self):
        """Remove cache entries.
        """
        self.cache.flush_all()

    def getCacheReport(self):
        """
        Reports on the contents of the cache.
        """
        stats = self.cache.get_stats()
        if stats and isinstance(stats, tuple):
            return stats[0]
        return stats

    def ZCache_invalidate(self, ob):
        """
        Invalidates the cache entries that apply to ob.
        """
        setattr(ob, self.cachecountervariable, getattr(ob, self.cachecountervariable, 0) + 1)

    def safeGetModTime(self, ob, mtime_func):
        """Because Cache.ZCacheable_getModTime can return setget attribute
        """
        # Similar to OFS/Cache ZCacheable_getModTime but making sure
        # mtime is float or int
        mtime = 0
        if mtime_func:
            # Allow mtime_func to influence the mod time.
            mtime = mtime_func()
        base = aq_base(ob)
        objecttime = getattr(base, '_p_mtime', mtime)
        if not isinstance(objecttime, (int, float)):
            objecttime = 0
        mtime = max(objecttime, mtime)
        klass = getattr(base, '__class__', None)
        if klass:
            klasstime = getattr(klass, '_p_mtime', mtime)
            if not isinstance(klasstime, (int, float)):
                klasstime = 0
            mtime = max(klasstime, mtime)
        return mtime

    def ZCache_get(self, ob, view_name='', keywords=None,
                   mtime_func=None, default=None):
        """
        Gets a cache entry or returns default.
        """
        oc = self.getObjectCacheEntries(ob)
        if oc is None:
            return default
        lastmod = self.safeGetModTime(ob, mtime_func)
        index = oc.aggregateIndex(view_name,
                                  aq_get(ob,'REQUEST',None),
                                  self.request_vars, keywords, 
                                  str(getattr(ob, '_memcachedcounter', '')))
        entry = oc.getEntry(lastmod, self.cache, index)
        if entry is _marker:
            return default
        return entry

    def ZCache_set(self, ob, data, view_name='', keywords=None,
                   mtime_func=None):
        """
        Sets a cache entry.
        """
        lastmod = self.safeGetModTime(ob, mtime_func)
        oc = self.getObjectCacheEntries(ob)
        index = oc.aggregateIndex(view_name,
                                  aq_get(ob,'REQUEST',None),
                                  self.request_vars, keywords,
                                  str(getattr(ob, '_memcachedcounter', '')))
        __traceback_info__ = ('/'.join(ob.getPhysicalPath()), data)
        oc.setEntry(lastmod, self.cache, index, data, self.max_age)

caches = {}

class MemcachedManager(CacheManager, SimpleItem):
    """Manage a cache which stores rendered data in memcached.

    This is intended to be used as a low-level cache for
    expensive Python code, not for objects published
    under their own URLs such as web pages.

    MemcachedManager *can* be used to cache complete publishable
    pages, such as DTMLMethods/Documents and Page Templates,
    but this is not advised: such objects typically do not attempt
    to cache important out-of-band data such as 3xx HTTP responses,
    and the client would get an erroneous 200 response.

    Such objects should instead be cached with an
    AcceleratedHTTPCacheManager and/or downstream
    caching.
    """

    __ac_permissions__ = (
        ('View management screens', ('getSettings',
                                     'manage_main',
                                     'manage_stats',
                                     'getCacheReport',
                                     )),
        ('Change cache managers', ('manage_editProps',),
         ('Manager',)),
        )

    manage_options = (
        {'label':'Properties', 'action':'manage_main'},
        {'label':'Statistics', 'action':'manage_stats'},
        ) + CacheManager.manage_options + SimpleItem.manage_options

    meta_type = 'Memcached Manager'

    def __init__(self, ob_id):
        self.id = ob_id
        self.title = ''
        self._settings = {
            'request_vars': ('AUTHENTICATED_USER',),
            'servers': ('127.0.0.1:11211',),
            'mirrors': (),
            'max_age': 3600,
            'debug': 0,
            }
        self.__cacheid = '%s_%f' % (id(self), time.time())

    def getId(self):
        """Get Object Id
        """
        return self.id

    ZCacheManager_getCache__roles__ = ()
    def ZCacheManager_getCache(self):
        key = (get_ident(), self.__cacheid)
        try:
            return caches[key]
        except KeyError:
            cache = Memcached()
            settings = self.getSettings()
            cache.initSettings(settings)
            caches[key] = cache
            return cache

    def getSettings(self):
        """Returns the current cache settings.
        """
        return self._settings.copy()

    manage_main = DTMLFile('dtml/propsMM', globals())

    def manage_editProps(self, title, settings=None, REQUEST=None):
        """Changes the cache settings.
        """
        if settings is None:
            settings = REQUEST
        self.title = str(title)
        request_vars = list(settings['request_vars'])
        request_vars.sort()
        servers = filter(None, list(settings['servers']))
        mirrors = filter(None, list(settings.get('mirrors',[])))
        debug = int(settings.get('debug', 0))
        self._settings = {
            'request_vars': tuple(request_vars),
            'servers': tuple(servers),
            'mirrors': tuple(mirrors),
            'max_age': int(settings['max_age']),
            'debug': debug,
            }

        settings = self.getSettings()
        for (tid, cid), cache in caches.items():
            if cid == self.__cacheid:
                cache.initSettings(settings)
        if REQUEST is not None:
            return self.manage_main(
                self, REQUEST, manage_tabs_message='Properties changed.')

    manage_stats = DTMLFile('dtml/statsMM', globals())

    def getCacheReport(self):
        """Cache Statistics
        """
        c = self.ZCacheManager_getCache()
        rval = c.getCacheReport()
        return rval

InitializeClass(MemcachedManager)

manage_addMemcachedManagerForm = DTMLFile('dtml/addMM', globals())

def manage_addMemcachedManager(self, id, REQUEST=None):
    """Add a Memcached Manager to the folder.
    """
    self._setObject(id, MemcachedManager(id))
    if REQUEST is not None:
        return self.manage_main(self, REQUEST)
