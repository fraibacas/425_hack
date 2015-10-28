import time
from Testing import ZopeTestCase
from Products.PythonScripts.PythonScript import PythonScript
import memcache
# Trick to make the local memcache become global memcache if present
import sys
sys.modules['memcache'] = memcache
sys.modules['pylibmc'] = memcache
from Products.MemcachedManager.MemcachedManager import MemcachedManager

class Dummy:

    meta_type="foo"

    def __init__(self, path):
        self.path = path

    def getPhysicalPath(self):
        return self.path.split('/')

    def absolute_url(self):
        return 'http://nohost%s' % self.path

    def __str__(self):
        return '<Dummy: %s>' % self.path

    __repr__ = __str__


class MemcachedManagerTestCase(ZopeTestCase.ZopeTestCase):

    def afterSetUp(self):
        self._cachemanager = MemcachedManager('cache')
        self._cache = self._cachemanager.ZCacheManager_getCache()
        self.folder.script = PythonScript('script')
        self._script = self.folder.script

    def beforeTearDown(self):
        self.dummySleep()
        self._cache.cleanup()
        memcache.DATA = {}
        self.dummySleep()

    def dummySleep(self, duration=0.5):
        if not hasattr(self._cache.cache, 'dummyclient'):time.sleep(duration)


    def setRequestVars(self, request_vars):
        settings = self._cachemanager.getSettings()
        settings['request_vars'] = request_vars
        self._cachemanager.manage_editProps('Cache', settings=settings)

    def setRefreshInterval(self, interval):
        settings = self._cachemanager.getSettings()
        settings['refresh_interval'] = interval
        self._cachemanager.manage_editProps('Cache', settings=settings)

    def setMaxAge(self, age):
        settings = self._cachemanager.getSettings()
        settings['max_age'] = age
        self._cachemanager.manage_editProps('Cache', settings=settings)

