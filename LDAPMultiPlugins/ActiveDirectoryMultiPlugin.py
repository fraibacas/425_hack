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
""" ActiveDirectoryUserFolder shim module

$Id: ActiveDirectoryMultiPlugin.py 2044 2010-11-18 12:53:21Z jens $
"""

from ldap.filter import filter_format
import logging
import os
from urllib import quote_plus

from Acquisition import aq_base
from App.class_init import default__class_init__ as InitializeClass
from App.Common import package_home
from App.special_dtml import DTMLFile
from AccessControl import ClassSecurityInfo
from zope.interface import implementedBy

from Products.LDAPUserFolder import manage_addLDAPUserFolder
from Products.LDAPUserFolder.utils import BINARY_ATTRIBUTES
from Products.PluggableAuthService.interfaces.plugins import \
     IUserEnumerationPlugin, IGroupsPlugin, IGroupEnumerationPlugin, \
     IRoleEnumerationPlugin
from Products.PluggableAuthService.utils import classImplements

from LDAPPluginBase import LDAPPluginBase


logger = logging.getLogger('event.LDAPMultiPlugin')
_dtmldir = os.path.join(package_home(globals()), 'dtml')
addActiveDirectoryMultiPluginForm = DTMLFile('addActiveDirectoryMultiPlugin',
                                             _dtmldir)

def manage_addActiveDirectoryMultiPlugin( self, id, title, LDAP_server
                             , login_attr
                             , uid_attr, users_base, users_scope, roles
                             , groups_base, groups_scope, binduid, bindpwd
                             , binduid_usage=1, rdn_attr='cn', local_groups=0
                             , use_ssl=0 , encryption='SHA', read_only=0
                             , self_signed_cert=0
                             , REQUEST=None
                             ):
    """ Factory method to instantiate a ActiveDirectoryMultiPlugin """
    # Make sure we really are working in our container (the 
    # PluggableAuthService object)
    self = self.this()

    # Value needs massaging, there's some magic transcending a simple true
    # or false expeced by the LDAP delegate :(
    if use_ssl:
        use_ssl = 1
    else:
        use_ssl = 0

    if self_signed_cert:
        self_signed_cert = 1
    else:
        self_signed_cert = 0
    
    # Instantiate the folderish adapter object
    lmp = ActiveDirectoryMultiPlugin(id, title=title)
    self._setObject(id, lmp)
    lmp = getattr(aq_base(self), id)
    lmp_base = aq_base(lmp)

    # Put the "real" LDAPUserFolder inside it
    manage_addLDAPUserFolder(lmp)
    luf = getattr(lmp_base, 'acl_users')

    host_elems = LDAP_server.split(':')
    host = host_elems[0]
    if len(host_elems) > 1:
        port = host_elems[1]
    else:
        if use_ssl:
            port = '636'
        else:
            port = '389'

    luf.manage_addServer(host, port=port, use_ssl=use_ssl, op_timeout=10, self_signed_cert=self_signed_cert)
    luf.manage_edit( title
                   , login_attr
                   , uid_attr
                   , users_base
                   , users_scope
                   , roles
                   , groups_base
                   , groups_scope
                   , binduid
                   , bindpwd
                   , binduid_usage=binduid_usage
                   , rdn_attr=rdn_attr
                   , local_groups=local_groups
                   , encryption=encryption
                   , read_only=read_only
                   , REQUEST=None
                   )              

    # clean out the __allow_groups__ bit because it is not needed here
    # and potentially harmful
    if hasattr(lmp_base, '__allow_groups__'):
        del lmp_base.__allow_groups__

    uf = lmp.acl_users
    uf._ldapschema =   { 'cn' : { 'ldap_name' : 'cn'
                                , 'friendly_name' : 'Canonical Name'
                                , 'multivalued' : ''
                                , 'public_name' : ''
                                }
                       , 'sn' : { 'ldap_name' : 'sn'
                                , 'friendly_name' : 'Last Name'
                                , 'multivalued' : ''
                                , 'public_name' : 'last_name'
                                }
                       }
    uf.manage_addLDAPSchemaItem('dn', 'Distinguished Name',
                                public_name='dn')
    uf.manage_addLDAPSchemaItem('sAMAccountName', 'Windows Login Name',
                                public_name='windows_login_name')
    uf.manage_addLDAPSchemaItem('objectGUID', 'AD Object GUID',
                                public_name='objectGUID')
    uf.manage_addLDAPSchemaItem('givenName', 'First Name',
                                public_name='first_name')
    uf.manage_addLDAPSchemaItem('sn', 'Last Name',
                                public_name='last_name')
    uf.manage_addLDAPSchemaItem('memberOf',
                                'Group DNs',
                                public_name='memberOf',
                                multivalued=True)

    if REQUEST is not None:
        REQUEST.RESPONSE.redirect('%s/manage_main' % self.absolute_url())

class ActiveDirectoryMultiPlugin(LDAPPluginBase):
    """ The adapter that mediates between the PAS and the LDAPUserFolder """
    security = ClassSecurityInfo()
    meta_type = 'ActiveDirectory Multi Plugin'

    _properties = LDAPPluginBase._properties + (
        {'id':'groupid_attr', 'type':'string', 'mode':'w'},
        {'id':'grouptitle_attr', 'type':'string', 'mode':'w'},
        {'id':'group_class', 'type':'string', 'mode':'w'},
        {'id':'group_recurse', 'type':'int', 'mode':'w'},
        {'id':'group_recurse_depth', 'type':'int', 'mode':'w'},
        )

    groupid_attr = 'objectGUID'
    grouptitle_attr = 'cn'
    group_class = 'group'
    group_recurse = 1
    group_recurse_depth = 1

    def __init__(self, id, title='', groupid_attr='objectGUID',
                 grouptitle_attr='cn', group_class='group', group_recurse=1, 
                 group_recurse_depth=1):
        """ Initialize a new instance """
        self.id = id
        self.title = title
        self.groupid_attr = groupid_attr
        self.grouptitle_attr = grouptitle_attr
        self.group_class = group_class
        self.group_recurse = group_recurse
        self.group_recurse_depth = group_recurse_depth

    security.declarePublic('getGroupsForPrincipal')
    def getGroupsForPrincipal(self, user, request=None, attr=None):
        """ Fulfill GroupsPlugin requirements """
        if attr is None:
            attr = self.groupid_attr

        acl = self._getLDAPUserFolder()

        if acl is None:
            return ()

        view_name = self.getId() + '_getGroupsForPrincipal'
        criteria = {'user_id':user.getId(), 'attr':attr}

        cached_info = self.ZCacheable_get(view_name = view_name,
                                          keywords = criteria,
                                          default = None)

        if cached_info is not None:
            logger.debug('returning cached results from getGroupsForPrincipal')
            return cached_info

        unmangled_userid = self._demangle(user.getId())
        if unmangled_userid is None:
            return ()

        ldap_user = acl.getUserById(unmangled_userid)
        if ldap_user is None:
            return ()

        cns = [ x.split(',')[0] for x in (ldap_user.memberOf or []) ]
        if not cns:
            return ()
        cns = [x.split('=')[1] for x in cns]

        # Add the optional group filter to limit groups that are returned
        extraGroupFilter = acl.getProperty('_extra_group_filter')

        cn_flts = [filter_format('(cn=%s)', (cn,)) for cn in cns]
        if extraGroupFilter:
            filt = '(&(objectClass=%s)(|%s)(&%s))' % (self.group_class, ''.join(cn_flts), extraGroupFilter)
        else:
            filt = '(&(objectClass=%s)(|%s))' % (self.group_class, ''.join(cn_flts))

        delegate = acl._delegate
        R = delegate.search(acl.groups_base, acl.groups_scope, filter=filt)

        if R['exception']:
            logger.error("Failed to locate groups for principal in %s "
                         "(scope=%s, filter=%s): %s",
                         acl.groups_base, acl.groups_scope, filt,
                         R['exception'])
            return ()
        if self.group_recurse:
            groups = self._recurseGroups(R['results'])
        else:
            groups = R['results']

        results = [ x[attr][0] for x in groups]

        self.ZCacheable_set(results, view_name=view_name, keywords=criteria)

        return results

    def _recurseGroups(self, ldap_results, temp=None, seen=None, depth=0):
        """ Given a set of LDAP result data for a group search, return
        the recursive group memberships for each group: arbitrarily
        expensive """
        if seen is None:
            seen = {}
        if temp is None:
            temp = []
        # Build a single filter so we can do it with a single search.
        filt_bits = []

        for result in ldap_results:
            dn = result['dn']
            
            if seen.has_key(dn):
                continue
            temp.append(result)
            seen[dn] = 1
            
            if result.has_key('memberOf'):
                for parent_dn in result['memberOf']:
                    filt = filter_format('(distinguishedName=%s)', (parent_dn,))
                    if filt in filt_bits:
                        continue
                    filt_bits.append(filt)

        if filt_bits:
            bits_s = ''.join(filt_bits)
            filt = "(&(objectClass=%s)(|%s))" % (self.group_class, bits_s)
            acl = self.acl_users
            delegate = acl._delegate
            R = delegate.search(acl.groups_base, acl.groups_scope, filter=filt)
            if R['exception']:
                logger.error("Failed to recursively search for group in %s "
                             "(scope=%s, filter=%s): %s",
                             acl.groups_base, acl.groups_scope, filt,
                             R['exception'])
            else:
                if depth < self.group_recurse_depth:    
                    self._recurseGroups(R['results'], temp, seen, depth + 1)

        return temp

    security.declarePrivate('enumerateUsers')
    def enumerateUsers( self
                      , id=None
                      , login=None
                      , exact_match=0
                      , sort_by=None
                      , max_results=None
                      , **kw
                      ):
        """ Fulfill the UserEnumerationPlugin requirements """
        view_name = self.getId() + '_enumerateUsers'
        criteria = {'id':id, 'login':login, 'exact_match':exact_match,
                    'sort_by':sort_by, 'max_results':max_results}
        criteria.update(kw)

        cached_info = self.ZCacheable_get(view_name = view_name,
                                          keywords = criteria,
                                          default = None)

        if cached_info is not None:
            logger.debug('returning cached results from enumerateUsers')
            return cached_info
        
        result = []
        acl = self._getLDAPUserFolder()
        login_attr = acl.getProperty('_login_attr')
        uid_attr = acl.getProperty('_uid_attr')
        plugin_id = self.getId()
        edit_url = '%s/%s/manage_userrecords' % (plugin_id, acl.getId())

        if login_attr in kw:
            login = kw[login_attr]
            del kw[login_attr]

        if uid_attr in kw:
            id = kw[uid_attr]
            del kw[uid_attr]

        if acl is None:
            return ()

        if exact_match:
            if id:
                ldap_user = acl.getUserById(id)
            elif login:
                ldap_user = acl.getUser(login)
            else:
                msg = 'Exact Match specified but no ID or Login given'
                raise ValueError, msg

            if ldap_user is not None:
                qs = 'user_dn=%s' % quote_plus(ldap_user.getUserDN())
                result.append( { 'id' : ldap_user.getId()
                               , 'login' : ldap_user.getProperty(login_attr)
                               , 'pluginid' : plugin_id
                               , 'title': ldap_user.getProperty(login_attr)
                               , 'editurl' : '%s?%s' % (edit_url, qs)
                               } ) 
        elif id or login or kw:
            l_results = []
            seen = []
            attrs = (uid_attr, login_attr)

            if id:
                l_results.extend(acl.findUser(uid_attr, id, attrs=attrs))

            if login:
                l_results.extend(acl.findUser(login_attr, login, attrs=attrs))

            for key, val in kw.items():
                l_results.extend(acl.findUser(key, val, attrs=attrs))

            for l_res in l_results:
                if l_res['dn'] not in seen and l_res.has_key(login_attr):
                    l_res['id'] = l_res[uid_attr]
                    l_res['login'] = l_res[login_attr]
                    l_res['pluginid'] = plugin_id
                    quoted_dn = quote_plus(l_res['dn'])
                    l_res['editurl'] = '%s?user_dn=%s' % (edit_url, quoted_dn)
                    result.append(l_res)
                    seen.append(l_res['dn'])

            if sort_by is not None:
                result.sort(lambda a, b: cmp( a.get(sort_by, '').lower()
                                            , b.get(sort_by, '').lower()
                                            ) )

            if isinstance(max_results, int) and len(result) > max_results:
                result = result[:max_results-1]

        else:
            result = []
            for uid, name in acl.getUserIdsAndNames():
                tmp = {}
                tmp['id'] = uid
                tmp['login'] = name
                tmp['pluginid'] = plugin_id
                tmp['editurl'] = None
                result.append(tmp)

            if sort_by is not None:
                result.sort(lambda a, b: cmp( a.get(sort_by, '').lower()
                                            , b.get(sort_by, '').lower()
                                            ) )

            if isinstance(max_results, int) and len(result) > max_results:
                result = result[:max_results-1]

        result =  tuple(result)

        self.ZCacheable_set(result, view_name=view_name, keywords=criteria)

        return result

    security.declarePrivate('enumerateGroups')
    def enumerateGroups( self
                       , id=None
                       , exact_match=0
                       , sort_by=None
                       , max_results=None
                       , **kw
                       ):
        """ Fulfill the RoleEnumerationPlugin requirements """
        view_name = self.getId() + '_enumerateGroups'
        criteria = {'id':id, 'exact_match':exact_match,
                    'sort_by':sort_by, 'max_results':max_results}
        criteria.update(kw)

        cached_info = self.ZCacheable_get(view_name = view_name,
                                          keywords = criteria,
                                          default = None)

        if cached_info is not None:
            logger.debug('returning cached results from enumerateGroups')
            return cached_info

        acl = self._getLDAPUserFolder()

        if acl is None:
            return ()

        if id is None and exact_match != 0:
            raise ValueError, 'Exact Match requested but no id provided'
        elif id is None:
            id = ''
            
        plugin_id = self.getId()

        filt = ['(objectClass=%s)' % self.group_class]
        if not id:
            filt.append('(%s=*)' % self.groupid_attr)
        elif exact_match:
            filt.append(filter_format('(%s=%s)',(self.groupid_attr, id)))
        elif id:
            filt.append(filter_format('(%s=*%s*)',(self.groupid_attr, id)))

        for (search_param, search_term) in kw.items():
            if search_term and exact_match:
                filt.append( filter_format( '(%s=%s)'
                                               , (search_param, search_term)
                                               ) )
            elif search_term:
                filt.append( filter_format( '(%s=*%s*)'
                                               , (search_param, search_term)
                                               ) )
            else:
                filt.append('(%s=*)' % search_param)

        filt = '(&%s)' % ''.join(filt)

        if self.groupid_attr.lower() in BINARY_ATTRIBUTES:
            convert_filter = False
        else:
            convert_filter = True

        delegate = acl._delegate
        R = delegate.search( acl.groups_base
                           , acl.groups_scope
                           , filter=filt
                           , convert_filter=convert_filter
                           )

        if R['exception']:
            logger.error("Failed to enumerate groups in %s "
                         "(scope=%s, filter=%s): %s",
                         acl.groups_base, acl.groups_scope, filt,
                         R['exception'])
            return ()

        groups = R['results']

        results = []
        for group in groups:
            tmp = {}
            tmp['title'] = '(Group) ' + group[self.grouptitle_attr][0]
            id = tmp['id'] = group[self.groupid_attr][0]
            tmp['pluginid'] = plugin_id
            results.append(tmp)

        if sort_by is not None:
            results.sort(lambda a, b: cmp( a.get(sort_by, '').lower()
                                          , b.get(sort_by, '').lower()
                                            ) )
        if isinstance(max_results, int) and len(results) > max_results:
            results = results[:max_results+1]

        results =  tuple(results)

        self.ZCacheable_set(results, view_name=view_name, keywords=criteria)

        return results

    security.declarePrivate('enumerateRoles')
    def enumerateRoles( self
                      , id=None
                      , exact_match=0
                      , sort_by=None
                      , max_results=None
                      , **kw
                      ):
        """ Fulfill the RoleEnumerationPlugin requirements """
        return []

classImplements( ActiveDirectoryMultiPlugin
               , IUserEnumerationPlugin
               , IGroupsPlugin
               , IGroupEnumerationPlugin
               , IRoleEnumerationPlugin
               , *implementedBy(LDAPPluginBase)
               )

InitializeClass(ActiveDirectoryMultiPlugin)

