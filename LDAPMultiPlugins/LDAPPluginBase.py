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
""" Base class for LDAPMultiPlugins-based PAS plugins

$Id: LDAPPluginBase.py 2057 2011-04-06 12:45:08Z jens $
"""

# General Python imports
import copy
import logging

# Zope imports
from AccessControl import ClassSecurityInfo
from AccessControl.SecurityManagement import getSecurityManager
from Acquisition import aq_base
from App.class_init import default__class_init__ as InitializeClass
from OFS.Cache import Cacheable
from OFS.Folder import Folder

from Products.PluggableAuthService.plugins.BasePlugin import BasePlugin
from Products.PluggableAuthService.interfaces.plugins import \
    IAuthenticationPlugin
from Products.PluggableAuthService.interfaces.plugins import \
    ICredentialsResetPlugin
from Products.PluggableAuthService.interfaces.plugins import IPropertiesPlugin
from Products.PluggableAuthService.interfaces.plugins import IRolesPlugin
from Products.PluggableAuthService.utils import classImplements

from Products.LDAPMultiPlugins.interfaces import ILDAPMultiPlugin

logger = logging.getLogger('event.LDAPMultiPlugin')


class LDAPPluginBase(Folder, BasePlugin, Cacheable):
    """ Base class for LDAP-based PAS plugins """
    security = ClassSecurityInfo()

    manage_options = ( BasePlugin.manage_options[:1]
                     + Folder.manage_options [:1]
                     + Folder.manage_options[2:]
                     + Cacheable.manage_options
                     )

    _properties = BasePlugin._properties + Folder._properties


    # default 'id' attribute for groups
    groupid_attr = 'cn'

    def __init__(self, id, title=''):
        """ Initialize a new instance """
        self.id = id
        self.title = title


    security.declarePrivate('_getLDAPUserFolder')
    def _getLDAPUserFolder(self):
        """ Safely retrieve a LDAPUserFolder to work with """
        embedded_luf = getattr(aq_base(self), 'acl_users', None)

        return embedded_luf


    security.declarePrivate('authenticateCredentials')
    def authenticateCredentials(self, credentials):
        """ Fulfill AuthenticationPlugin requirements """
        acl = self._getLDAPUserFolder()
        login = credentials.get('login')
        password = credentials.get('password')

        if not acl or not login or not password:
            return None, None

        session_data = self.session_data_manager.getSessionData()
        user = acl.getUser(login, pwd=password, session_data=session_data)

        if user is None:
            return None
        # update the user properties from the ldap
        schema = acl.getSchemaConfig()
        ufolder = self.dmd.ZenUsers.getUserSettings(user.getId())
        properties = user._properties
        logger.info("Syncing properties from LDAP for %s ", user.getId())
        for key, config in schema.iteritems():
            propertykey = config['ldap_name']
            ufolderkey = config['public_name']
            value = properties.get(propertykey, None)
            if ufolderkey:
                logger.debug("Updating UserFolder property %s with value %s", ufolderkey, value)
                setattr(ufolder, ufolderkey, value)
        return (user.getId(), user.getUserName())


    security.declarePrivate('resetCredentials')
    def resetCredentials(self, request, response):
        """ Fulfill CredentialsResetPlugin requirements """
        user = getSecurityManager().getUser()
        acl = self._getLDAPUserFolder()

        if user:
            acl._expireUser(user)


    security.declarePrivate('getPropertiesForUser')
    def getPropertiesForUser(self, user, request=None):
        """ Fullfill PropertiesPlugin requirements """
        acl = self._getLDAPUserFolder()

        if acl is None:
            return {}

        unmangled_userid = self._demangle(user.getId())
        if unmangled_userid is None:
            return {}

        ldap_user = acl.getUserById(unmangled_userid)

        if ldap_user is None:
            return {}

        # XXX Direct attribute access. Waaa!
        properties = copy.deepcopy(ldap_user._properties)

        # Need to clean up: The propertysheet mechanism will
        # blow up if "None" is encountered
        for key, val in properties.items():
            if val is None:
                properties[key] = ''

        return properties


    security.declarePrivate('getRolesForPrincipal')
    def getRolesForPrincipal(self, user, request=None):
        """ Fullfill RolesPlugin requirements """
        acl = self._getLDAPUserFolder()

        if acl is None:
            return ()

        unmangled_userid = self._demangle(user.getId())
        if unmangled_userid is None:
            return ()

        ldap_user = acl.getUserById(unmangled_userid)
        if ldap_user is None:
            return ()

        groups = self.getGroupsForPrincipal(user, request)
        roles = list(acl._mapRoles(groups))
        roles.extend(acl._roles)

        return tuple(roles)


    security.declarePrivate('_demangle')
    def _demangle(self, princid):
        # Sanity check
        if not isinstance(princid, basestring):
            return None

        # User must start with our prefix (which is likely to be blank anyway)
        if not princid.startswith(self.prefix):
            return None
        return princid[len(self.prefix):]

    # Helper methods for simple group caching
    security.declarePrivate('_getGroupInfoCacheKey')
    def _getGroupInfoCacheKey(self, gid):
        """_getGroupInfoCacheKey(id) -> (view_name, keywords)

        given a group id, return view_name and keywords to be used when
        querying and storing into the group cache
        """
        view_name = self.getId() + '__GroupInfoCache'
        keywords = { 'id' : gid }
        return view_name, keywords

    security.declarePrivate('_setGroupInfoCache')
    def _setGroupInfoCache(self, info):
        """Cache a group info"""
        gid = info['id']
        view_name, keywords = self._getGroupInfoCacheKey(gid)
        self.ZCacheable_set(info, view_name=view_name, keywords=keywords)

    security.declarePrivate('_getGroupInfoCache')
    def _getGroupInfoCache(self, gid, default=None):
        """Retrieve a group info from cache, given its group id.

        Returns None or the passed-in default if the cache
        has no group with such id
        """
        view_name, keywords = self._getGroupInfoCacheKey(gid)
        result = self.ZCacheable_get( view_name=view_name
                                    , keywords=keywords
                                    , default=default
                                    )
        return result


classImplements( LDAPPluginBase
               , IAuthenticationPlugin
               , ICredentialsResetPlugin
               , IPropertiesPlugin
               , IRolesPlugin
               , ILDAPMultiPlugin
               )

InitializeClass(LDAPPluginBase)
