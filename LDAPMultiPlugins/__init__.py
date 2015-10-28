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
""" LDAPMultiPlugins product initialization

$Id: __init__.py 1709 2009-02-17 13:49:17Z jens $
"""

from AccessControl.Permissions import add_user_folders
from Products.PluggableAuthService.PluggableAuthService import \
        registerMultiPlugin

from Products.LDAPMultiPlugins.LDAPMultiPlugin import addLDAPMultiPluginForm
from Products.LDAPMultiPlugins.LDAPMultiPlugin import LDAPMultiPlugin
from Products.LDAPMultiPlugins.LDAPMultiPlugin import manage_addLDAPMultiPlugin
from Products.LDAPMultiPlugins.ActiveDirectoryMultiPlugin import \
    ActiveDirectoryMultiPlugin
from Products.LDAPMultiPlugins.ActiveDirectoryMultiPlugin import \
    addActiveDirectoryMultiPluginForm
from Products.LDAPMultiPlugins.ActiveDirectoryMultiPlugin import \
    manage_addActiveDirectoryMultiPlugin

registerMultiPlugin(LDAPMultiPlugin.meta_type)
registerMultiPlugin(ActiveDirectoryMultiPlugin.meta_type)

def initialize(context):
    """ Initialize the LDAPMultiPlugin 
    """

    context.registerClass( LDAPMultiPlugin
                         , permission=add_user_folders
                         , constructors=( addLDAPMultiPluginForm
                                        , manage_addLDAPMultiPlugin
                                        )
                         , icon='www/ldapmultiplugin.png'
                         , visibility=None
                         )

    context.registerClass( ActiveDirectoryMultiPlugin
                         , permission=add_user_folders
                         , constructors=( addActiveDirectoryMultiPluginForm
                                     , manage_addActiveDirectoryMultiPlugin
                                     )
                         , icon='www/admultiplugin.png'
                         , visibility=None
                         )
