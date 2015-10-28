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
""" LDAPMultiPlugin and ActiveDirectoryMultiPlugin unit tests

$Id: test_LDAPMultiPlugins.py 1970 2010-05-30 11:36:24Z jens $
"""

import unittest


class LMPBaseTests(unittest.TestCase):

    def _makeOne(self):
        return self._getTargetClass()('testplugin')

    def _getTargetClass(self):
        from Products.LDAPMultiPlugins.LDAPPluginBase import LDAPPluginBase
        return LDAPPluginBase

    def test_interfaces(self):
        from Products.LDAPMultiPlugins.interfaces import ILDAPMultiPlugin
        from Products.PluggableAuthService.interfaces.plugins import \
             IUserEnumerationPlugin
        from Products.PluggableAuthService.interfaces.plugins import \
            IGroupsPlugin
        from Products.PluggableAuthService.interfaces.plugins import \
            IGroupEnumerationPlugin
        from Products.PluggableAuthService.interfaces.plugins import \
            IRoleEnumerationPlugin
        from zope.interface.verify import verifyClass

        verifyClass(ILDAPMultiPlugin, self._getTargetClass())

        verifyClass(IUserEnumerationPlugin, self._getTargetClass())
        verifyClass(IGroupsPlugin, self._getTargetClass())
        verifyClass(IGroupEnumerationPlugin, self._getTargetClass())
        verifyClass(IRoleEnumerationPlugin, self._getTargetClass())

    def test_demangle_invalid_userid(self):
        plugin = self._makeOne()
        plugin.prefix = 'prefix_'

        self.assertEquals(plugin._demangle(None), None)
        self.assertEquals(plugin._demangle('incorrectprefix'), None)
        self.assertEquals(plugin._demangle('prefix_user1'), 'user1')


class ADMPTests(LMPBaseTests):

    def _getTargetClass(self):
        from Products.LDAPMultiPlugins.ActiveDirectoryMultiPlugin import \
             ActiveDirectoryMultiPlugin       
        return ActiveDirectoryMultiPlugin


class LMPTests(LMPBaseTests):

    def _getTargetClass(self):
        from Products.LDAPMultiPlugins.LDAPMultiPlugin import LDAPMultiPlugin
        return LDAPMultiPlugin


def test_suite():
    return unittest.TestSuite((
        unittest.makeSuite(ADMPTests),
        unittest.makeSuite(LMPTests),
        ))

if __name__ == '__main__':
    unittest.main(defaultTest='test_suite') 

