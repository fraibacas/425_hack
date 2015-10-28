#
# Setup tests
#

from Testing import ZopeTestCase

ZopeTestCase.installProduct('MemcachedManager')


class TestSetup(ZopeTestCase.ZopeTestCase):

    def afterSetUp(self):
        pass

    def testAddCacheManager(self):
        factory = self.folder.manage_addProduct['MemcachedManager']
        factory.manage_addMemcachedManager(id='memcache')
        self.failUnless('memcache' in self.folder.objectIds())


def test_suite():
    from unittest import TestSuite, makeSuite
    suite = TestSuite()
    suite.addTest(makeSuite(TestSetup))
    return suite
