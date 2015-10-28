#! /usr/bin/env python
##############################################################################
# 
# Copyright (C) Zenoss, Inc. 2008, 2011, all rights reserved.
# 
# This content is made available according to terms specified in
# License.zenoss under the directory where your Zenoss product is installed.
# 
##############################################################################


__doc__ = """zensyslog

Turn syslog messages into events.

"""

import time
import socket
import os
import logging

from twisted.internet.protocol import DatagramProtocol
from twisted.internet import reactor, defer, udp
from twisted.python import failure

import Globals
import zope.interface
import zope.component
from zope.interface import implements

from Products.ZenHub.PBDaemon import EVENT_FLOW_THROTTLE
from Products.ZenHub.interfaces import ICollectorEventTransformer, \
                                       TRANSFORM_CONTINUE, \
                                       TRANSFORM_DROP
from Products.ZenCollector.daemon import CollectorDaemon
from Products.ZenCollector.interfaces import ICollector, ICollectorPreferences,\
                                             IEventService, \
                                             IScheduledTask, IStatisticsService
from Products.ZenCollector.tasks import SimpleTaskFactory,\
                                        SimpleTaskSplitter,\
                                        BaseTask, TaskStates
from Products.ZenUtils.observable import ObservableMixin

from Products.ZenEvents.SyslogProcessing import SyslogProcessor

from Products.ZenUtils.Utils import zenPath
from Products.ZenUtils.IpUtil import asyncNameLookup

from Products.ZenEvents.EventServer import Stats
from Products.ZenUtils.Utils import unused
from Products.ZenCollector.services.config import DeviceProxy
unused(Globals, DeviceProxy)

COLLECTOR_NAME = 'zensyslog'
log = logging.getLogger("zen.%s" % COLLECTOR_NAME)


class SyslogPreferences(object):
    zope.interface.implements(ICollectorPreferences)

    def __init__(self):
        """
        Constructs a new PingCollectionPreferences instance and
        provides default values for needed attributes.
        """
        self.collectorName = COLLECTOR_NAME
        self.defaultRRDCreateCommand = None
        self.configCycleInterval = 20 # minutes
        self.cycleInterval = 5 * 60 # seconds

        # The configurationService attribute is the fully qualified class-name
        # of our configuration service that runs within ZenHub
        self.configurationService = 'Products.ZenHub.services.SyslogConfig'

        # Will be filled in based on buildOptions
        self.options = None

        self.configCycleInterval = 20*60

    def postStartupTasks(self):
        task = SyslogTask(COLLECTOR_NAME, configId=COLLECTOR_NAME)
        yield task

    def buildOptions(self, parser):
        """
        Command-line options to be supported
        """
        SYSLOG_PORT = 514
        try:
            SYSLOG_PORT = socket.getservbyname('syslog', 'udp')
        except socket.error:
            pass

        parser.add_option('--parsehost', dest='parsehost',
                           action='store_true', default=False,
                           help='Try to parse the hostname part of a syslog HEADER')
        parser.add_option('--stats', dest='stats',
                           action='store_true', default=False,
                           help='Print statistics to log every 2 secs')
        parser.add_option('--logorig', dest='logorig',
                           action='store_true', default=False,
                           help='Log the original message')
        parser.add_option('--logformat', dest='logformat',
                           default='human',
                           help='Human-readable (/var/log/messages) or raw (wire)')
        parser.add_option('--minpriority', dest='minpriority',
                           default=6, type='int',
                           help='Minimum priority message that zensyslog will accept')
        parser.add_option('--syslogport', dest='syslogport',
                           default=SYSLOG_PORT, type='int',
                           help='Port number to use for syslog events')
        parser.add_option('--listenip', dest='listenip',
                           default='0.0.0.0',
                           help='IP address to listen on. Default is %default')
        parser.add_option('--useFileDescriptor',
                            dest='useFileDescriptor', type='int',
                           help='Read from an existing connection rather opening a new port.'
                           , default=None)
        parser.add_option('--noreverseLookup', dest='noreverseLookup',
                           action='store_true', default=False,
                           help="Don't convert the remote device's IP address to a hostname.")
        parser.add_option('--syslogfilterfile',
                            dest='syslogFilterFile',
                            type='string',
                            help=("File that contains syslog eventclasskeys to keep, should be in $ZENHOME/etc. If"
                                  " hubenabledfilter is set, the filter will only be enabled if zenhub "
                                  " sends an event throttle or pause message"),
                            default=None)
        parser.add_option('--hubenabledfilter', dest='hubEnabledFilter',
                           action='store_true', default=False,
                           help='Syslog filter enabled by hub to throttle events')

    def postStartup(self):
        daemon = zope.component.getUtility(ICollector)
        daemon.defaultPriority = 1
        
        # add our collector's custom statistics
        statService = zope.component.queryUtility(IStatisticsService)
        statService.addStatistic("events", "COUNTER")


class SyslogTask(BaseTask, DatagramProtocol):
    """
    Listen for syslog messages and turn them into events
    Connects to the SyslogConfig service in zenhub.
    """
    zope.interface.implements(IScheduledTask)

    SYSLOG_DATE_FORMAT = '%b %d %H:%M:%S'
    SAMPLE_DATE = 'Apr 10 15:19:22'

    def __init__(self, taskName, configId,
                 scheduleIntervalSeconds=3600, taskConfig=None):
        BaseTask.__init__(self, taskName, configId,
                 scheduleIntervalSeconds, taskConfig)
        self.log = log

        # Needed for interface
        self.name = taskName
        self.configId = configId
        self.state = TaskStates.STATE_IDLE
        self.interval = scheduleIntervalSeconds
        self._preferences = taskConfig
        self._daemon = zope.component.getUtility(ICollector)
        self._eventService = zope.component.queryUtility(IEventService)
        self._statService = zope.component.queryUtility(IStatisticsService)
        self._preferences = self._daemon

        self.options = self._daemon.options

        self.stats = Stats()

        if not self.options.useFileDescriptor\
             and self.options.syslogport < 1024:
            self._daemon.openPrivilegedPort('--listen', '--proto=udp',
                                    '--port=%s:%d'
                                     % (self.options.listenip,
                                    self.options.syslogport))
        self._daemon.changeUser()
        self.minpriority = self.options.minpriority
        self.processor = None

        if self.options.logorig:
            self.olog = logging.getLogger('origsyslog')
            self.olog.setLevel(20)
            self.olog.propagate = False
            lname = zenPath('log/origsyslog.log')
            hdlr = logging.FileHandler(lname)
            hdlr.setFormatter(logging.Formatter('%(message)s'))
            self.olog.addHandler(hdlr)

        if self.options.useFileDescriptor is not None:
            self.useUdpFileDescriptor(int(self.options.useFileDescriptor))
        else:
            reactor.listenUDP(self.options.syslogport, self,
                              interface=self.options.listenip)

        #   yield self.model().callRemote('getDefaultPriority')
        self.processor = SyslogProcessor(self._eventService.sendEvent,
                    self.options.minpriority, self.options.parsehost,
                    self.options.monitor, self._daemon.defaultPriority)

    def doTask(self):
        """
        This is a wait-around task since we really are called
        asynchronously.
        """
        return defer.succeed("Waiting for syslog messages...")

    def useUdpFileDescriptor(self, fd):
        s = socket.fromfd(fd, socket.AF_INET, socket.SOCK_DGRAM)
        os.close(fd)
        port = s.getsockname()[1]
        transport = udp.Port(port, self)
        s.setblocking(0)
        transport.socket = s
        transport.fileno = s.fileno
        transport.connected = 1
        transport._realPortNumber = port
        self.transport = transport
        # hack around startListening not being called
        self.numPorts = 1
        transport.startReading()

    def expand(self, msg, client_address):
        """
        Expands a syslog message into a string format suitable for writing
        to the filesystem such that it appears the same as it would
        had the message been logged by the syslog daemon.
        
        @param msg: syslog message
        @type msg: string
        @param client_address: IP info of the remote device (ipaddr, port)
        @type client_address: tuple of (string, number)
        @return: message
        @rtype: string
        """
        # pri := facility * severity
        stop = msg.find('>')

        # check for a datestamp.  default to right now if date not present
        start = stop + 1
        stop = start + len(SyslogTask.SAMPLE_DATE)
        dateField = msg[start:stop]
        try:
            date = time.strptime(dateField,
                                 SyslogTask.SYSLOG_DATE_FORMAT)
            year = time.localtime()[0]
            date = (year, ) + date[1:]
            start = stop + 1
        except ValueError:

        # date not present, so use today's date
            date = time.localtime()

        # check for a hostname.  default to localhost if not present
        stop = msg.find(' ', start)
        if msg[stop - 1] == ':':
            hostname = client_address[0]
        else:
            hostname = msg[start:stop]
            start = stop + 1

        # the message content
        body = msg[start:]

        # assemble the message
        prettyTime = time.strftime(SyslogTask.SYSLOG_DATE_FORMAT, date)
        message = '%s %s %s' % (prettyTime, hostname, body)
        return message

    def datagramReceived(self, msg, client_address):
        """
        Consume the network packet
        
        @param msg: syslog message
        @type msg: string
        @param client_address: IP info of the remote device (ipaddr, port)
        @type client_address: tuple of (string, number)
        """
        (ipaddr, port) = client_address
        if self.options.logorig:
            if self.options.logformat == 'human':
                message = self.expand(msg, client_address)
            else:
                message = msg
            self.olog.info(message)

        if self.options.noreverseLookup:
            d = defer.succeed(ipaddr)
        else:
            d = asyncNameLookup(ipaddr)
        d.addBoth(self.gotHostname, (msg, ipaddr, time.time()))

    def gotHostname(self, response, data):
        """
        Send the resolved address, if possible, and the event via the thread
        
        @param response: Twisted response
        @type response: Twisted response
        @param data: (msg, ipaddr, rtime)
        @type data: tuple of (string, string, datetime object)
        """
        (msg, ipaddr, rtime) = data
        if isinstance(response, failure.Failure):
            host = ipaddr
        else:
            host = response
        if self.processor:
            self.processor.process(msg, ipaddr, host, rtime)
            totalTime, totalEvents, maxTime = self.stats.report()
            stat = self._statService.getStatistic("events")
            stat.value = totalEvents

    def displayStatistics(self):
        totalTime, totalEvents, maxTime = self.stats.report()
        display = "%d events processed in %.2f seconds" % (
                      totalEvents,
                      totalTime)
        if totalEvents > 0:
            display += """
%.5f average seconds per event
Maximum processing time for one event was %.5f""" % (
                       (totalTime / totalEvents), maxTime)
        return display

    def cleanup(self):
        status = self.displayStatistics()
        self.log.info(status)


class SyslogConfigTask(ObservableMixin):
    """
    Receive a configuration object containing the default priority
    """
    zope.interface.implements(IScheduledTask)

    def __init__(self, taskName, configId,
                 scheduleIntervalSeconds=3600, taskConfig=None):
        super(SyslogConfigTask, self).__init__()

        # Needed for ZCA interface contract
        self.name = taskName
        self.configId = configId
        self.state = TaskStates.STATE_IDLE
        self.interval = scheduleIntervalSeconds
        self._preferences = taskConfig
        self._daemon = zope.component.getUtility(ICollector)

        self._daemon.defaultPriority = self._preferences.defaultPriority

    def doTask(self):
        return defer.succeed("Already updated default syslog priority...")

    def cleanup(self):
        pass

class SysLogFilter(object):
    implements(ICollectorEventTransformer)
    """
    Interface used to perform filtering of events at the collector. This could be
    used to drop events, transform event content, etc.

    These transformers are run sequentially before a fingerprint is generated for
    the event, so they can set fields which are used by an ICollectorEventFingerprintGenerator.

    The priority of the event transformer (the transformers are executed in
            ascending order using the weight of each filter).

    """
    weight = 1
    def __init__(self):
        self._daemon = None
        self._eventService = None
        self._hubEnabled = False
        self._enableRate = None
        self._syslogKeys = set()
        self._initialized = False

    def _read_syslog_keys(self):
        sysLogKeys = set()
        fileName = self._daemon.options.syslogFilterFile
        if fileName:
            path = zenPath('etc', fileName)
            if os.path.exists(path):
                with open(path) as syslogFile:
                    for line in syslogFile:
                        line = line.strip()
                        if not line.startswith('#'):
                            sysLogKeys.add(line)
            else:
                log.warn("Config file {0} was not found; no syslog filters added.".format(path))
        return sysLogKeys

    def initialize(self):
        self._daemon = zope.component.getUtility(ICollector)
        self._eventService = zope.component.queryUtility(IEventService)
        self._hubEnabled = self._daemon.options.hubEnabledFilter
        #read syslog eventclasskeys from file --syslogfilterfile
        self._syslogKeys = self._read_syslog_keys()
        self._initialized = True

    def transform(self, event):
        """
        Performs any transforms of the specified event at the collector.

        @param event: The event to transform.
        @type event: dict
        @return: Returns TRANSFORM_CONTINUE if this event should be forwarded on
                 to the next transformer in the sequence, TRANSFORM_STOP if no
                 further transformers should be performed on this event, and
                 TRANSFORM_DROP if the event should be dropped.
        @rtype: int
        """
        result = TRANSFORM_CONTINUE
        if self._initialized and self._syslogKeys:
            if not self._hubEnabled or self._daemon.getEventFlow() >= EVENT_FLOW_THROTTLE:
                eventClassKey = event.get('eventClassKey', None)
                log.info("Filtering syslog %s", eventClassKey)
                if self._dropLog(eventClassKey):
                    log.warn("Dropping syslog %s", eventClassKey)
                    result = TRANSFORM_DROP
        return result

    def _dropLog(self, syslogkey):
        return syslogkey not in self._syslogKeys

class SyslogDaemon(CollectorDaemon):

    _frameworkFactoryName = "nosip"

    def __init__(self, *args, **kwargs):
        self._sysLogFilter = SysLogFilter()
        zope.component.provideUtility(self._sysLogFilter, ICollectorEventTransformer)
        super(SyslogDaemon, self).__init__(*args, **kwargs)
        self._sysLogFilter.initialize()

if __name__=='__main__':
    myPreferences = SyslogPreferences()
    myTaskFactory = SimpleTaskFactory(SyslogConfigTask)
    myTaskSplitter = SimpleTaskSplitter(myTaskFactory)
    daemon = SyslogDaemon(myPreferences, myTaskSplitter)
    daemon.run()
