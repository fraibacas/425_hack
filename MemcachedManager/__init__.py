"""
$Id: __init__.py 42560 2007-05-23 18:10:39Z dreamcatcher $
"""

import logging
logger = logging.getLogger("MemcachedManager")

def initialize(context):
    try:
        import MemcachedManager
    except ImportError:
        logger.error('Unable to import MemcachedManager. '
                     'You may need to install the memcache '
                     'client python library. See README.txt '
                     'for instructions.')
        return

    context.registerClass(
        MemcachedManager.MemcachedManager,
        constructors = (
        MemcachedManager.manage_addMemcachedManagerForm,
        MemcachedManager.manage_addMemcachedManager),
        icon="cache.gif"
        )

