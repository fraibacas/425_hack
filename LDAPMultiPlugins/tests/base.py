##############################################################################
#
# Copyright (c) 2005-2009 Jens Vagelpohl and Contributors. All Rights Reserved.
#
# This software is subject to the provisions of the Zope Public License,
# Version 2.1 (ZPL).  A copy of the ZPL should accompany this distribution.
# THIS SOFTWARE IS PROVIDED "AS IS" AND ANY AND ALL EXPRESS OR IMPLIED
# WARRANTIES ARE DISCLAIMED, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF TITLE, MERCHANTABILITY, AGAINST INFRINGEMENT, AND FITNESS
# FOR A PARTICULAR PURPOSE.
#
##############################################################################
""" Test helper classes

$Id: base.py 1823 2009-11-24 15:15:21Z jens $
"""

import unittest

from OFS.Folder import Folder
from Products.Five import zcml

try:
    from Products.GenericSetup.testing import BodyAdapterTestCase
    from Products.GenericSetup.testing import ExportImportZCMLLayer
    from Products.GenericSetup.tests.common import BaseRegistryTests
    
    
    class LMPXMLAdapterTestsBase(BodyAdapterTestCase, unittest.TestCase):
    
        layer = ExportImportZCMLLayer
    
        def _getTargetClass(self):
            from Products.LDAPMultiPlugins.exportimport \
                    import LDAPMultiPluginXMLAdapter
    
            return LDAPMultiPluginXMLAdapter
    
        def setUp(self):
            import Products.LDAPMultiPlugins
            import Products.LDAPUserFolder
            super(LMPXMLAdapterTestsBase, self).setUp()
            try:
                import Products.CMFCore
                zcml.load_config('meta.zcml', Products.CMFCore)
            except ImportError:
                pass
            zcml.load_config('configure.zcml', Products.LDAPUserFolder)
            zcml.load_config('configure.zcml', Products.LDAPMultiPlugins)
    
    
    class _LDAPMultiPluginsSetup(BaseRegistryTests):
    
        layer = ExportImportZCMLLayer
    
        def _initSite(self, use_changed=False):
            self.root.site = Folder(id='site')
            site = self.root.site
            site._setObject('tested',self._getTargetClass()('tested'))
    
            if use_changed:
                self._edit()
    
            return site
except ImportError:
    LMPXMLAdapterTestsBase = _LDAPMultiPluginsSetup = unittest.TestCase


