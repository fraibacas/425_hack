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
""" LDAPMultiPlugins GenericSetup support

$Id: exportimport.py 1959 2010-05-28 12:38:57Z jens $
"""

from zope.component import adapts

from Products.GenericSetup.interfaces import ISetupEnviron
from Products.GenericSetup.utils import exportObjects
from Products.GenericSetup.utils import importObjects
from Products.GenericSetup.utils import ObjectManagerHelpers
from Products.GenericSetup.utils import PropertyManagerHelpers
from Products.GenericSetup.utils import XMLAdapterBase

from Products.LDAPMultiPlugins.interfaces import ILDAPMultiPlugin


class LDAPMultiPluginXMLAdapter( XMLAdapterBase
                               , ObjectManagerHelpers
                               , PropertyManagerHelpers
                               ):
    """ Export/import LDAPMultiPlugins plugins
    """
    adapts(ILDAPMultiPlugin, ISetupEnviron)

    _LOGGER_ID = 'ldapmultiplugins'

    def _exportNode(self):
        """ Export the object as a DOM node.
        """
        node = self._getObjectNode('object')
        node.appendChild(self._extractProperties())
        node.appendChild(self._extractObjects())

        self._logger.info('LDAPMultiPlugin exported.')
        return node

    def _importNode(self, node):
        """ Import the object from the DOM node.
        """
        if self.environ.shouldPurge():
            self._purgeProperties()
            self._purgeObjects()

        self._initProperties(node)
        self._initObjects(node)

        self._logger.info('LDAPMultiPlugin imported.')

    node = property(_exportNode, _importNode)

    def _exportBody(self):
        """ Export the object as a file body.
        """
        if not ILDAPMultiPlugin.providedBy(self.context):
            return None

        return XMLAdapterBase._exportBody(self)

    body = property(_exportBody, XMLAdapterBase._importBody)


def importLDAPMultiPlugins(context):
    """ Import LDAPMultiPlugin settings from an XML file

    When using this step directly, the setup tool is expected to be
    inside the PluggableAuthService object
    """
    pas = context.getSite()
    ldapmultiplugins = [ x for x in context.getSite().objectValues()
                                        if ILDAPMultiPlugin.providedBy(x) ]

    if not ldapmultiplugins:
        context.getLogger('ldapmultiplugins').debug('Nothing to export.')

    for plugin in ldapmultiplugins:
        importObjects(plugin, '', context)


def exportLDAPMultiPlugins(context):
    """ Export LDAPMultiPlugin settings to an XML file

    When using this step directly, the setup tool is expected to be
    inside the PluggableAuthService object
    """
    pas = context.getSite()
    ldapmultiplugins = [ x for x in context.getSite().objectValues()
                                        if ILDAPMultiPlugin.providedBy(x) ]

    if not ldapmultiplugins:
        context.getLogger('ldapmultiplugins').debug('Nothing to export.')

    for plugin in ldapmultiplugins:
        exportObjects(plugin, '', context)

