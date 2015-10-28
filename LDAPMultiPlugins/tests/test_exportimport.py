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
""" Export/import tests

$Id: test_exportimport.py 1798 2009-06-02 15:53:44Z jens $
"""

import unittest

try:
    from Products.GenericSetup.tests.common import DummyExportContext
    from Products.GenericSetup.tests.common import DummyImportContext 

    def test_suite():
        return unittest.TestSuite((
            unittest.makeSuite(LDAPMultiPluginXMLAdapterTests),
            unittest.makeSuite(ActiveDirectoryMultiPluginXMLAdapterTests),
            unittest.makeSuite(LDAPMultiPluginExportTests),
            unittest.makeSuite(ADMultiPluginExportTests),
            unittest.makeSuite(LDAPMultiPluginImportTests),
            unittest.makeSuite(ADMultiPluginImportTests),
        ))

except ImportError:
    def test_suite():
        return unittest.TestSuite()

from Products.LDAPMultiPlugins.tests.base import _LDAPMultiPluginsSetup
from Products.LDAPMultiPlugins.tests.base import LMPXMLAdapterTestsBase


class LDAPMultiPluginXMLAdapterTests(LMPXMLAdapterTestsBase):

    def setUp(self):
        from Products.LDAPMultiPlugins.LDAPMultiPlugin import LDAPMultiPlugin
        LMPXMLAdapterTestsBase.setUp(self)
        self._obj = LDAPMultiPlugin('tested')
        self._BODY = _LDAPMULTIPLUGIN_BODY

class ActiveDirectoryMultiPluginXMLAdapterTests(LMPXMLAdapterTestsBase):

    def setUp(self):
        from Products.LDAPMultiPlugins.ActiveDirectoryMultiPlugin import \
            ActiveDirectoryMultiPlugin
        LMPXMLAdapterTestsBase.setUp(self)
        self._obj = ActiveDirectoryMultiPlugin('tested')
        self._BODY = _ACTIVEDIRECTORYMULTIPLUGIN_BODY


class LDAPMultiPluginExportTests(_LDAPMultiPluginsSetup):

    def _getTargetClass(self):
        from Products.LDAPMultiPlugins.LDAPMultiPlugin import LDAPMultiPlugin
        return LDAPMultiPlugin

    def _edit(self):
        plugin = self.root.site.tested
        plugin.title = 'Plugin Title'
        plugin.prefix = 'plugin_prefix'

    def test_unchanged(self):
        from Products.LDAPMultiPlugins.exportimport import \
            exportLDAPMultiPlugins

        site = self._initSite(use_changed=False)
        context = DummyExportContext(site)
        exportLDAPMultiPlugins(context)

        self.assertEqual(len(context._wrote), 1)
        filename, text, content_type = context._wrote[0]
        self.assertEqual(filename, 'tested.xml')
        self._compareDOM(text, _LDAPMULTIPLUGIN_BODY)
        self.assertEqual(content_type, 'text/xml')

    def test_changed(self):
        from Products.LDAPMultiPlugins.exportimport import \
            exportLDAPMultiPlugins

        site = self._initSite(use_changed=True)
        context = DummyExportContext(site)
        exportLDAPMultiPlugins(context)

        self.assertEqual(len(context._wrote), 1)
        filename, text, content_type = context._wrote[0]
        self.assertEqual(filename, 'tested.xml')
        self._compareDOM(text, _CHANGED_LMP_EXPORT)
        self.assertEqual(content_type, 'text/xml')


class ADMultiPluginExportTests(_LDAPMultiPluginsSetup):

    def _getTargetClass(self):
        from Products.LDAPMultiPlugins.ActiveDirectoryMultiPlugin import \
            ActiveDirectoryMultiPlugin
        return ActiveDirectoryMultiPlugin

    def _edit(self):
        plugin = self.root.site.tested
        plugin.title = 'Plugin Title'
        plugin.prefix = 'plugin_prefix'
        plugin.groupid_attr = 'cn'
        plugin.grouptitle_attr = 'sn'
        plugin.group_class = 'groupOfNames'
        plugin.group_recurse = 0
        plugin.group_recurse_depth = 0

    def test_unchanged(self):
        from Products.LDAPMultiPlugins.exportimport import \
            exportLDAPMultiPlugins

        site = self._initSite(use_changed=False)
        context = DummyExportContext(site)
        exportLDAPMultiPlugins(context)

        self.assertEqual(len(context._wrote), 1)
        filename, text, content_type = context._wrote[0]
        self.assertEqual(filename, 'tested.xml')
        self._compareDOM(text, _ACTIVEDIRECTORYMULTIPLUGIN_BODY)
        self.assertEqual(content_type, 'text/xml')

    def test_changed(self):
        from Products.LDAPMultiPlugins.exportimport import \
            exportLDAPMultiPlugins

        site = self._initSite(use_changed=True)
        context = DummyExportContext(site)
        exportLDAPMultiPlugins(context)

        self.assertEqual(len(context._wrote), 1)
        filename, text, content_type = context._wrote[0]
        self.assertEqual(filename, 'tested.xml')
        self._compareDOM(text, _CHANGED_AD_EXPORT)
        self.assertEqual(content_type, 'text/xml')


class LDAPMultiPluginImportTests(_LDAPMultiPluginsSetup):

    def _getTargetClass(self):
        from Products.LDAPMultiPlugins.LDAPMultiPlugin import LDAPMultiPlugin
        return LDAPMultiPlugin

    def test_normal(self):
        from Products.LDAPMultiPlugins.exportimport import \
            importLDAPMultiPlugins

        site = self._initSite()
        plugin = site.tested

        context = DummyImportContext(site)
        context._files['tested.xml'] = _CHANGED_LMP_EXPORT
        importLDAPMultiPlugins(context)

        self.assertEquals(plugin.title, 'Plugin Title')
        self.assertEquals(plugin.prefix, 'plugin_prefix')


class ADMultiPluginImportTests(_LDAPMultiPluginsSetup):

    def _getTargetClass(self):
        from Products.LDAPMultiPlugins.ActiveDirectoryMultiPlugin import \
            ActiveDirectoryMultiPlugin
        return ActiveDirectoryMultiPlugin

    def test_normal(self):
        from Products.LDAPMultiPlugins.exportimport import \
            importLDAPMultiPlugins

        site = self._initSite()
        plugin = site.tested

        context = DummyImportContext(site)
        context._files['tested.xml'] = _CHANGED_AD_EXPORT
        importLDAPMultiPlugins(context)

        self.assertEquals(plugin.title, 'Plugin Title')
        self.assertEquals(plugin.prefix, 'plugin_prefix')
        self.assertEquals(plugin.groupid_attr, 'cn')
        self.assertEquals(plugin.grouptitle_attr, 'sn')
        self.assertEquals(plugin.group_class, 'groupOfNames')
        self.assertEquals(plugin.group_recurse, 0)
        self.assertEquals(plugin.group_recurse_depth, 0)



_LDAPMULTIPLUGIN_BODY = """\
<?xml version="1.0"?>
<object name="tested" meta_type="LDAP Multi Plugin">
 <property name="prefix"></property>
 <property name="title"></property>
</object>
"""

_ACTIVEDIRECTORYMULTIPLUGIN_BODY = """\
<?xml version="1.0"?>
<object name="tested" meta_type="ActiveDirectory Multi Plugin">
 <property name="prefix"></property>
 <property name="title"></property>
 <property name="groupid_attr">objectGUID</property>
 <property name="grouptitle_attr">cn</property>
 <property name="group_class">group</property>
 <property name="group_recurse">1</property>
 <property name="group_recurse_depth">1</property>
</object>
"""

_CHANGED_LMP_EXPORT = """\
<?xml version="1.0"?>
<object name="tested" meta_type="LDAP Multi Plugin">
 <property name="prefix">plugin_prefix</property>
 <property name="title">Plugin Title</property>
</object>
"""

_CHANGED_AD_EXPORT = """\
<?xml version="1.0"?>
<object name="tested" meta_type="ActiveDirectory Multi Plugin">
 <property name="prefix">plugin_prefix</property>
 <property name="title">Plugin Title</property>
 <property name="groupid_attr">cn</property>
 <property name="grouptitle_attr">sn</property>
 <property name="group_class">groupOfNames</property>
 <property name="group_recurse">0</property>
 <property name="group_recurse_depth">0</property>
</object>
"""
