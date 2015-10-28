#!/opt/zenoss/bin/python

import logging
import Globals
import transaction
from datetime import datetime, timedelta

from Products.ZenUtils.ZCmdBase import ZCmdBase
zodb = ZCmdBase(noopts=True)

class FlushJobsCatalog(ZCmdBase):

    def flushCatalog(self):
        if not self.options.untilTime:
            self.parser.error('Missing untiltime argument!')
            return 0
        untiltime = int(self.options.untilTime)
        utime = timedelta(days = untiltime)
        jobm = zodb.dmd.JobManager
        jobm.deleteUntil(utime)
        transaction.commit()


    def buildOptions(self):
        ZCmdBase.buildOptions(self)
        self.parser.add_option('-i', '-u', '--untiltime',
                    dest='untilTime',
                    help='Delete all jobs older than untiltime')
        self.parser.set_defaults(logseverity=logging.DEBUG)


if __name__ == "__main__":
    fc = FlushJobsCatalog()
    fc.flushCatalog()
