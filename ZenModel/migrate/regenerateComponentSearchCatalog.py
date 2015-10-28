##############################################################################
# 
# Copyright (C) Zenoss, Inc. 2014, all rights reserved.
# 
# This content is made available according to terms specified in
# License.zenoss under the directory where your Zenoss product is installed.
# 
##############################################################################


__doc__ = """ Regenerates the componentSearch catalog for all 
devices after adding the id index to the catalog """

from Products.ZenModel.migrate import Migrate
import sys

class RegenerateComponentSearchCatalog(Migrate.Step):

    version = Migrate.Version(4, 2, 5)

    def _update_progress(self, done, total):
        sys.stdout.write("\rProgress: [ Processed {0} devices of {1} ]".format(done, total))
        sys.stdout.flush()
        if done == total:
            print ""

    def cutover(self, dmd):
    	""" For each device, deletes the componentSearch catalog and recreates it """
        devices_to_migrate = []
        for d in dmd.Devices.getSubDevicesGen():
            if not d.hasObject('componentSearch') or "id" not in d.componentSearch.indexes():
                devices_to_migrate.append(d)

    	number_of_devices = len(devices_to_migrate)

        if number_of_devices > 0:
            print "Regenerating componentSearch catalog for {0} devices. This may take some time...".format(number_of_devices)
            devices_processed = 0
            for d in devices_to_migrate:
                if d.hasObject('componentSearch'):
                    d._delObject('componentSearch')
                d._create_componentSearch()
                devices_processed = devices_processed + 1
                self._update_progress(devices_processed, number_of_devices)

RegenerateComponentSearchCatalog()
