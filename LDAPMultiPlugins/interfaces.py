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
""" Interfaces for LDAPMultiPlugins package classes

$Id: interfaces.py 1694 2009-02-08 08:21:45Z jens $
"""

from zope.interface import Interface


class ILDAPMultiPlugin(Interface):
    """ Marker interface for the LDAPMultiPlugins plugin classes
    """
