===========================
 Products.LDAPMultiPlugins
===========================

.. contents::

The LDAPMultiPlugins provides PluggableAuthService plugins that use LDAP as 
the backend for the services they provide. The PluggableAuthService is a 
Zope user folder product that can be extended in modular fashion using 
various plugins.


Bug tracker
===========
Please post questions, bug reports or feature requests to the bug tracker
at https://bugs.launchpad.net/products.ldapmultiplugins


SVN version
===========
You can retrieve the latest code from Subversion using setuptools or
zc.buildout via this URL:

http://svn.dataflake.org/svn/Products.LDAPMultiPlugins/trunk#egg=Products.LDAPMultiPlugins


Special features - Active Directory Multi Plugin
================================================

Properties of the ADMultiPlugin instance:

- groupid_attr - the LDAP attribute used for group ids.

- grouptitle_attr - the LDAP attribute used to compose group titles.

- group_class - the LDAP class of group objects.

- group_recurse - boolean indicating whether to determine group
  memberships of a user by unrolling nested group relationships
  (expensive). This feature is not guaranteed to work at this moment.


Active Directory configuration hints
====================================

In order for groups support to work correctly, you may have to set the
following properties. Every situation is different, but this has helped
some people succeed:

- On the "Properties" tab for the ActiveDirectoryMultiPlugin, set the
  groupid_attr property to "name".

- On the contained LDAPUserFolder's "Configure" tab, choose a 
  property other than "objectGUID", e.g. "sAMAccountName" for the
  User ID property. To get to the LDAPUserFolder, click on the
  ActiveDirectoryMultiPlugin "Content" tab.

Please see README.ActiveDirectory from the LDAPUserFolder package for
additional information.

