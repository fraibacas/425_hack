##############################################################################
# 
# Copyright (C) Zenoss, Inc. 2015, all rights reserved.
# 
# This content is made available according to terms specified in
# License.zenoss under the directory where your Zenoss product is installed.
# 
##############################################################################


__doc__='''

 
'''
import Migrate
import logging
import transaction
from Products.ZenModel.LinkManager import DrawNetwork

log = logging.getLogger('zen.migrate')


class AddZdrawMapLinks(Migrate.Step):
    version = Migrate.Version(4, 2, 5)
    
    def cutover(self, dmd):
        
        if not hasattr(dmd.ZenLinkManager, 'networks'):
            dmd.ZenLinkManager.networks = DrawNetwork()
            log.info("Pulling zDrawMapLinks to the datastructure, this may take some time")
            for net in dmd.Networks.getSubNetworks():
                network = net.getPrimaryUrlPath()
                dmd.ZenLinkManager.networks.add_net(network, getattr(dmd.unrestrictedTraverse(net.getPrimaryUrlPath()), 'zDrawMapLinks'))
                
AddZdrawMapLinks()
