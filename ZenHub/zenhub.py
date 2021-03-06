#! /usr/bin/env python
##############################################################################
# 
# Copyright (C) Zenoss, Inc. 2007, all rights reserved.
# 
# This content is made available according to terms specified in
# License.zenoss under the directory where your Zenoss product is installed.
# 
##############################################################################


"""zenhub daemon

Provide remote, authenticated, and possibly encrypted two-way
communications with the Model and Event databases.
"""
import Globals

if __name__ == "__main__":
    # Install the 'best' reactor available, BUT only if run as a script.
    from Products.ZenHub import installReactor
    installReactor()

from XmlRpcService import XmlRpcService

import collections
import socket
import time
import signal
import cPickle as pickle
import os
import subprocess
from random import choice

from email.mime.text import MIMEText
from twisted.mail.smtp import sendmail

from twisted.cred import portal, checkers, credentials
from twisted.spread import pb, banana
banana.SIZE_LIMIT = 1024 * 1024 * 10

from twisted.internet import reactor, protocol, defer, task
from twisted.internet.utils import getProcessOutput

from twisted.python import failure
from twisted.web import server, xmlrpc
from twisted.internet.error import ProcessExitedAlready
from zope.event import notify
from zope.interface import implements
from zope.component import getUtility, getUtilitiesFor, adapts, getAdapter
from zope.component.interfaces import Interface
from ZODB.POSException import POSKeyError

from zenoss.protocols.twisted.amqp import AMQPFactory
from zenoss.protocols.interfaces import IAMQPConnectionInfo, IQueueSchema
from zenoss.protocols.interfaces import IAMQPChannelAdapter

from Products.DataCollector.Plugins import loadPlugins
from Products.Five import zcml
from Products.ZenUtils.ZCmdBase import ZCmdBase
from Products.ZenUtils.Utils import zenPath, getExitMessage, unused, load_config, load_config_override, ipv6_available, atomicWrite
from Products.ZenUtils.DaemonStats import DaemonStats
from Products.ZenEvents.Event import Event, EventHeartbeat
from Products.ZenEvents.ZenEventClasses import App_Start
from Products.ZenMessaging.queuemessaging.interfaces import IEventPublisher
from Products.ZenRelations.PrimaryPathObjectManager import PrimaryPathObjectManager
from Products.ZenModel.DeviceComponent import DeviceComponent
from Products.ZenHub.services.RenderConfig import RenderConfig
from Products.ZenHub.interfaces import IInvalidationProcessor, IServiceAddedEvent, IHubCreatedEvent, IHubWillBeCreatedEvent, IInvalidationOid, IHubConfProvider, IHubHeartBeatCheck
from Products.ZenHub.interfaces import IParserReadyForOptionsEvent, IInvalidationFilter
from Products.ZenHub.interfaces import FILTER_INCLUDE, FILTER_EXCLUDE, IQueueSizeProvider

from Products.ZenHub.WorkerSelection import WorkerSelector

from Products.ZenHub.PBDaemon import RemoteBadMonitor,EVENT_FLOW_NORMAL, EVENT_FLOW_PAUSE, EVENT_FLOW_THROTTLE, EVENT_FLOWS, EVENT_FLOWS_MAP
pb.setUnjellyableForClass(RemoteBadMonitor, RemoteBadMonitor)

from BTrees.IIBTree import IITreeSet

# Due to the manipulation of sys.path during the loading of plugins,
# we can get ObjectMap imported both as DataMaps.ObjectMap and the
# full-path from Products.  The following gets the class registered
# with the jelly serialization engine under both names:
#
#  1st: get Products.DataCollector.plugins.DataMaps.ObjectMap
from Products.DataCollector.plugins.DataMaps import ObjectMap
#  2nd: get DataMaps.ObjectMap
import sys
sys.path.insert(0, zenPath('Products', 'DataCollector', 'plugins'))
import DataMaps
unused(DataMaps, ObjectMap)

from Products.ZenHub import XML_RPC_PORT
from Products.ZenHub import PB_PORT
from Products.ZenHub import ZENHUB_ZENRENDER

OPTION_STATE = 1
CONNECT_TIMEOUT = 60

HubWorklistItem = collections.namedtuple('HubWorklistItem', 'recvtime deferred priority servicename instance method args')
WorkerStats = collections.namedtuple('WorkerStats', 'status description lastupdate previdle')
LastCallReturnValue = collections.namedtuple('LastCallReturnValue', 'returnvalue')

try:
    NICE_PATH = subprocess.check_output('which nice', shell=True).strip()
except Exception:
    NICE_PATH = None

class AuthXmlRpcService(XmlRpcService):
    """Provide some level of authentication for XML/RPC calls"""

    def __init__(self, dmd, checker):
        XmlRpcService.__init__(self, dmd)
        self.checker = checker


    def doRender(self, unused, request):
        """
        Call the inherited render engine after authentication succeeds.
        See @L{XmlRpcService.XmlRpcService.Render}.
        """
        return XmlRpcService.render(self, request)


    def unauthorized(self, request):
        """
        Render an XMLRPC error indicating an authentication failure.
        @type request: HTTPRequest
        @param request: the request for this xmlrpc call.
        @return: None
        """
        self._cbRender(xmlrpc.Fault(self.FAILURE, "Unauthorized"), request)


    def render(self, request):
        """
        Unpack the authorization header and check the credentials.
        @type request: HTTPRequest
        @param request: the request for this xmlrpc call.
        @return: NOT_DONE_YET
        """
        auth = request.received_headers.get('authorization', None)
        if not auth:
            self.unauthorized(request)
        else:
            try:
                type, encoded = auth.split()
                if type not in ('Basic',):
                    self.unauthorized(request)
                else:
                    user, passwd = encoded.decode('base64').split(':')
                    c = credentials.UsernamePassword(user, passwd)
                    d = self.checker.requestAvatarId(c)
                    d.addCallback(self.doRender, request)
                    def error(unused, request):
                        self.unauthorized(request)
                    d.addErrback(error, request)
            except Exception:
                self.unauthorized(request)
        return server.NOT_DONE_YET


class HubAvitar(pb.Avatar):
    """
    Connect collectors to their configuration Services
    """

    def __init__(self, hub):
        self.hub = hub


    def perspective_ping(self):
        return 'pong'

    def perspective_getService(self,
                               serviceName,
                               instance = None,
                               listener = None):
        """
        Allow a collector to find a Hub service by name.  It also
        associates the service with a collector so that changes can be
        pushed back out to collectors.

        @type serviceName: string
        @param serviceName: a name, like 'EventService'
        @type instance: string
        @param instance: the collector's instance name, like 'localhost'
        @type listener: a remote reference to the collector
        @param listener: the callback interface to the collector
        @return a remote reference to a service
        """
        try:
            service = self.hub.getService(serviceName, instance)
        except Exception:
            self.hub.log.exception("Failed to get service '%s'", serviceName)
            return None
        else:
            if service is not None and listener:
                service.addListener(listener)
            return service

    def perspective_reportingForWork(self, worker):
        """
        Allow a worker register for work.

        @type worker: a pb.RemoteReference
        @param worker: a reference to zenhubworker
        @return None
        """
        worker.busy = False
        self.hub.workers.append(worker)
        def removeWorker(worker):
            if worker in self.hub.workers:
                self.hub.workers.remove(worker)
        worker.notifyOnDisconnect(removeWorker)


class ServiceAddedEvent(object):
    implements(IServiceAddedEvent)
    def __init__(self, name, instance):
        self.name = name
        self.instance = instance


class HubWillBeCreatedEvent(object):
    implements(IHubWillBeCreatedEvent)
    def __init__(self, hub):
        self.hub = hub


class HubCreatedEvent(object):
    implements(IHubCreatedEvent)
    def __init__(self, hub):
        self.hub = hub

class ParserReadyForOptionsEvent(object):
    implements(IParserReadyForOptionsEvent)
    def __init__(self, parser):
        self.parser = parser

class HubRealm(object):
    """
    Following the Twisted authentication framework.
    See http://twistedmatrix.com/projects/core/documentation/howto/cred.html
    """
    implements(portal.IRealm)

    def __init__(self, hub):
        self.hubAvitar = HubAvitar(hub)

    def requestAvatar(self, collName, mind, *interfaces):
        if pb.IPerspective not in interfaces:
            raise NotImplementedError
        return pb.IPerspective, self.hubAvitar, lambda:None


class WorkerInterceptor(pb.Referenceable):
    """Redirect service requests to one of the worker processes. Note
    that everything else (like change notifications) go through
    locally hosted services."""

    callTime = 0.

    def __init__(self, zenhub, service):
        self.zenhub = zenhub
        self.service = service

    def remoteMessageReceived(self, broker, message, args, kw):
        "Intercept requests and send them down to workers"
        svc = str(self.service.__class__).rpartition('.')[0]
        instance = self.service.instance
        args = broker.unserialize(args)
        kw = broker.unserialize(kw)
        # hide the types in the args: subverting the jelly protection mechanism,
        # but the types just passed through and the worker may not have loaded
        # the required service before we try passing types for that service
        # PB has a 640k limit, not bytes but len of sequences. When args are
        # pickled the resulting string may be larger than 640k, split into
        # 100k chunks
        pickledArgs = pickle.dumps( (args, kw), pickle.HIGHEST_PROTOCOL )
        chunkedArgs=[]
        chunkSize = 102400
        while pickledArgs:
            chunk = pickledArgs[:chunkSize]
            chunkedArgs.append(chunk)
            pickledArgs = pickledArgs[chunkSize:]

        result = self.zenhub.deferToWorker( (svc, instance, message, chunkedArgs) )
        return broker.serialize(result, self.perspective)

    def __getattr__(self, attr):
        "Implement the HubService interface by forwarding to the local service"
        return getattr(self.service, attr)


class _ZenHubWorklist(object):

    def __init__(self):
        self.eventworklist = []
        self.otherworklist = []
        self.applyworklist = []

        #priority lists for eventual task selection. All queues are appended in case
        #any of them are empty.
        self.eventPriorityList = [self.eventworklist, self.otherworklist, self.applyworklist]
        self.otherPriorityList = [self.otherworklist, self.applyworklist, self.eventworklist]
        self.applyPriorityList = [self.applyworklist, self.eventworklist, self.otherworklist]
        self.dispatch = {
            'sendEvents': self.eventworklist,
            'applyDataMaps': self.applyworklist
        }

    def __getitem__(self, item):
        return self.dispatch.get(item, self.otherworklist)

    def __len__(self):
        return len(self.eventworklist) + len(self.otherworklist) + len(self.applyworklist)

    def pop(self):
        """
        Select a single task to be distributed to a worker. We prioritize tasks as follows:
            sendEvents > configuration service calls > applyDataMaps
        To prevent starving any queue in an event storm, we randomize the task selection,
        preferring tasks according to the above priority.
        """
        eventchain = filter(None, self.eventPriorityList)
        otherchain = filter(None, self.otherPriorityList)
        applychain = filter(None, self.applyPriorityList)
        seq = choice([eventchain]*4 +
                      [otherchain]*2 +
                      [applychain]
                                 )
        ret = seq[0].pop(0)
        return ret

    def push(self, job):
        self[job.method].insert(0, job)

    def append(self, job):
        self[job.method].append(job)

class ZenHub(ZCmdBase):
    """
    Listen for changes to objects in the Zeo database and update the
    collectors' configuration.

    The remote collectors connect the ZenHub and request configuration
    information and stay connected.  When changes are detected in the
    Zeo database, configuration updates are sent out to collectors
    asynchronously.  In this way, changes made in the web GUI can
    affect collection immediately, instead of waiting for a
    configuration cycle.

    Each collector uses a different, pluggable service within ZenHub
    to translate objects into configuration and data.  ZenPacks can
    add services for their collectors.  Collectors communicate using
    Twisted's Perspective Broker, which provides authenticated,
    asynchronous, bidirectional method invocation.

    ZenHub also provides an XmlRPC interface to some common services
    to support collectors written in other languages.
    
    ZenHub does very little work in its own process, but instead dispatches
    the work to a pool of zenhubworkers, running zenhubworker.py. zenhub
    manages these workers with 3 data structures:
    - workers - a list of remote PB instances
    - worker_processes - a set of WorkerRunningProtocol instances
    - workerprocessmap - a dict mapping pid to process instance created
        by reactor.spawnprocess
    Callbacks and handlers that detect worker shutdown update these
    structures automatically. ONLY ONE HANDLER must take care of restarting
    new workers, to avoid accidentally spawning too many workers. This
    handler also verifies that zenhub is not in the process of shutting 
    down, so that callbacks triggered during daemon shutdown don't keep
    starting new workers.
    
    TODO: document invalidation workers
    """

    totalTime = 0.
    totalEvents = 0
    totalCallTime = 0.
    name = 'zenhub'

    def __init__(self):
        """
        Hook ourselves up to the Zeo database and wait for collectors
        to connect.
        """
        # list of remote worker references
        self.workers = []
        self.workTracker = {}
        self.workList = _ZenHubWorklist()
        # set of worker processes
        self.worker_processes=set()
        # map of worker pids -> worker processes
        self.workerprocessmap = {}
        self.shutdown = False
        self.counters = collections.Counter()
        # control flow
        self._pauseEvents = False
        self._eventFlow = EVENT_FLOW_NORMAL
        self._amqpFactory = None

        ZCmdBase.__init__(self)
        import Products.ZenHub
        load_config("hub.zcml", Products.ZenHub)
        notify(HubWillBeCreatedEvent(self))

        #Worker selection handler
        self.workerselector = WorkerSelector(self.options)
        self.workList.log = self.log

        # make sure we don't reserve more than n-1 workers for events
        maxReservedEventsWorkers = 0
        if self.options.workers:
            maxReservedEventsWorkers = self.options.workers-1
        if self.options.workersReservedForEvents > maxReservedEventsWorkers:
            self.options.workersReservedForEvents = maxReservedEventsWorkers
            self.log.info("reduced number of workers reserved for sending events to %d",
                            self.options.workersReservedForEvents)

        self.zem = self.dmd.ZenEventManager
        loadPlugins(self.dmd)
        self.services = {}

        er = HubRealm(self)
        checker = self.loadChecker()
        pt = portal.Portal(er, [checker])
        interface = '::' if ipv6_available() else ''
        pbport = reactor.listenTCP(self.options.pbport, pb.PBServerFactory(pt), interface=interface)
        import socket
        pbport.socket.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, OPTION_STATE)
        pbport.socket.setsockopt(socket.SOL_TCP, socket.TCP_KEEPIDLE, CONNECT_TIMEOUT)
        interval = max(CONNECT_TIMEOUT / 4, 10)
        pbport.socket.setsockopt(socket.SOL_TCP, socket.TCP_KEEPINTVL, interval)
        pbport.socket.setsockopt(socket.SOL_TCP, socket.TCP_KEEPCNT, 2)

        xmlsvc = AuthXmlRpcService(self.dmd, checker)
        reactor.listenTCP(self.options.xmlrpcport, server.Site(xmlsvc), interface=interface)

        #start listening for zenrender requests
        if self.options.graph_proxy:
            self.renderConfig = RenderConfig(self.dmd, ZENHUB_ZENRENDER )

        # responsible for sending messages to the queues
        import Products.ZenMessaging.queuemessaging
        load_config_override('twistedpublisher.zcml', Products.ZenMessaging.queuemessaging)
        notify(HubCreatedEvent(self))
        self.sendEvent(eventClass=App_Start,
                       summary="%s started" % self.name,
                       severity=0)

        self._initialize_invalidation_filters()
        reactor.callLater(self.options.invalidation_poll_interval, self.processQueue)

        self.rrdStats = self.getRRDStats()

        if self.options.workers:
            self.workerconfig = zenPath('var', 'zenhub', '%s_worker.conf' % self._getConf().id)
            self._createWorkerConf()
            for i in range(self.options.workers):
                self.createWorker()

            # start cyclic call to giveWorkToWorkers
            reactor.callLater(2, self.giveWorkToWorkers, True)

        # set up SIGUSR2 handling
        try:
            signal.signal(signal.SIGUSR2, self.sighandler_USR2)
        except ValueError:
            # If we get called multiple times, this will generate an exception:
            # ValueError: signal only works in main thread
            # Ignore it as we've already set up the signal handler.
            pass

    def sighandler_USR2(self, signum, frame):
        #log zenhub's worker stats
        self._workerStats()

        # send SIGUSR2 signal to all workers
        for worker in self.workerprocessmap.values():
            try:
                worker.signalProcess(signal.SIGUSR2)
                time.sleep(0.5)
            except Exception:
                pass

    def stop(self):
        self.shutdown = True

    def _getConf(self):
        confProvider = IHubConfProvider(self)
        return confProvider.getHubConf()

    def getRRDStats(self):
        """
        Return the most recent RRD statistic information.
        """
        rrdStats = DaemonStats()
        perfConf = self._getConf()

        from Products.ZenModel.BuiltInDS import BuiltInDS
        threshs = perfConf.getThresholdInstances(BuiltInDS.sourcetype)
        createCommand = getattr(perfConf, 'defaultRRDCreateCommand', None)
        rrdStats.config(perfConf.id, 'zenhub', threshs, createCommand)

        return rrdStats

    @defer.inlineCallbacks
    def processQueue(self):
        """
        Periodically process database changes

        @return: None
        """
        now = time.time()
        try:
            self.log.debug("[processQueue] syncing....")
            yield self.async_syncdb()  # reads the object invalidations
            self.log.debug("[processQueue] synced")
        except Exception:
            self.log.warn("Unable to poll invalidations, will try again.")
        else:
            try:
                self.doProcessQueue()
            except Exception, ex:
                self.log.exception("Unable to poll invalidations.")
        reactor.callLater(self.options.invalidation_poll_interval, self.processQueue)
        self.totalEvents += 1
        self.totalTime += time.time() - now

    def _initialize_invalidation_filters(self):
        filters = (f for n, f in getUtilitiesFor(IInvalidationFilter))
        self._invalidation_filters = []
        for fltr in sorted(filters, key=lambda f:getattr(f, 'weight', 100)):
            fltr.initialize(self.dmd)
            self._invalidation_filters.append(fltr)
        self.log.debug('Registered %s invalidation filters.' %
                       len(self._invalidation_filters))

    def _filter_oids(self, oids):
        app = self.dmd.getPhysicalRoot()
        i = 0
        for oid in oids:
            i += 1
            try:
                obj = app._p_jar[oid]
            except POSKeyError:
                # State is gone from the database. Send it along.
                yield oid
            else:
                if isinstance(obj, (PrimaryPathObjectManager, DeviceComponent)):
                    try:
                        obj = obj.__of__(self.dmd).primaryAq()
                    except (AttributeError, KeyError):
                        # It's a delete. This should go through.
                        yield oid
                    else:
                        included = True
                        for fltr in self._invalidation_filters:
                            result = fltr.include(obj)
                            if result in (FILTER_INCLUDE, FILTER_EXCLUDE):
                                included = (result == FILTER_INCLUDE)
                                break
                        if included:
                            oids = self._transformOid(oid, obj)
                            if oids:
                                for oid in oids:
                                    yield oid

    def _transformOid(self, oid, obj):
        oidTransform = IInvalidationOid(obj)
        newOids = oidTransform.transformOid(oid)
        if isinstance(newOids, str):
            newOids = [newOids]
        for newOid in newOids:
            yield newOid

    def doProcessQueue(self):
        """
        Perform one cycle of update notifications.

        @return: None
        """
        changes_dict = self.storage.poll_invalidations()
        if changes_dict is not None:
            processor = getUtility(IInvalidationProcessor)
            d = processor.processQueue(tuple(set(self._filter_oids(changes_dict))))
            def done(n):
                if n:
                    self.log.debug('Processed %s oids' % n)
            d.addCallback(done)


    def sendEvent(self, **kw):
        """
        Useful method for posting events to the EventManager.

        @type kw: keywords (dict)
        @param kw: the values for an event: device, summary, etc.
        @return: None
        """
        if not 'device' in kw:
            kw['device'] = self.options.monitor
        if not 'component' in kw:
            kw['component'] = self.name
        try:
            self.zem.sendEvent(Event(**kw))
        except Exception:
            self.log.exception("Unable to send an event")

    def loadChecker(self):
        """
        Load the password file

        @return: an object satisfying the ICredentialsChecker
        interface using a password file or an empty list if the file
        is not available.  Uses the file specified in the --passwd
        command line option.
        """
        try:
            checker = checkers.FilePasswordDB(self.options.passwordfile)
            # grab credentials for the workers to login
            u, p = checker._loadCredentials().next()
            self.workerUsername, self.workerPassword = u, p
            return checker
        except Exception, ex:
            self.log.exception("Unable to load %s", self.options.passwordfile)
        return []

    def getService(self, name, instance):
        """
        Helper method to load services dynamically for a collector.
        Returned instances are cached: reconnecting collectors will
        get the same service object.

        @type name: string
        @param name: the dotted-name of the module to load
        (uses @L{Products.ZenUtils.Utils.importClass})
        @param instance: string
        @param instance: each service serves only one specific collector
        instances (like 'localhost').  instance defines the collector's
        instance name.
        @return: a service loaded from ZenHub/services or one of the zenpacks.
        """
        # Sanity check the names given to us
        if not self.dmd.Monitors.Performance._getOb(instance, False):
            raise RemoteBadMonitor( "The provided performance monitor '%s'" % \
                 self.options.monitor + " is not in the current list" )

        try:
            return self.services[name, instance]

        except KeyError:
            from Products.ZenUtils.Utils import importClass
            try:
                ctor = importClass(name)
            except ImportError:
                ctor = importClass('Products.ZenHub.services.%s' % name, name)
            try:
                svc = ctor(self.dmd, instance)
            except Exception:
                self.log.exception("Failed to initialize %s", ctor)
                # Module can't be used, so unload it.
                if ctor.__module__ in sys.modules:
                    del sys.modules[ctor.__module__]
                return None
            else:
                if self.options.workers:
                    svc = WorkerInterceptor(self, svc)
                self.services[name, instance] = svc
                notify(ServiceAddedEvent(name, instance))
                return svc

    def deferToWorker(self, args):
        """Take a remote request and queue it for worker processes.

        @type args: tuple
        @param args: the arguments to the remote_execute() method in the worker
        @return: a Deferred for the eventual results of the method call

        """
        d = defer.Deferred()
        svcName, instance, method = args[:3]
        service = self.getService(svcName, instance).service
        priority = service.getMethodPriority(method)

        self.workList.append(HubWorklistItem(time.time(), d, priority, svcName, instance, method, args))

        self.giveWorkToWorkers()
        return d

    def updateStatusAtStart(self, wId, job):
        now = time.time()
        jobDesc = "%s:%s.%s" % (job.instance, job.servicename, job.method)
        stats = self.workTracker.pop(wId, None)
        idletime = 0
        if stats:
            idletime = now - stats.lastupdate
        self.log.debug("Giving %s to worker %d, (%s)", job.method, wId, jobDesc)
        self.workTracker[wId] = WorkerStats('Busy', jobDesc, now, idletime)

    def updateStatusAtFinish(self, wId, error=None):
        now = time.time()
        stats = self.workTracker.pop(wId, None)
        if stats:
            elapsed  = now - stats.lastupdate
            self.log.debug("worker %s, work %s finished in %s" % (wId, stats.description, elapsed))
        self.workTracker[wId] = WorkerStats('Error: %s' % error if error else 'Idle',
                                            stats.description, now, 0)


    def giveWorkToWorkers(self, requeue=False):
        """Parcel out a method invocation to an available worker process
        """
        if self.workList:
            self.log.debug("worklist has %d items", len(self.workList))
        incompleteJobs = []
        while self.workList:
            if all(w.busy for w in self.workers):
                self.log.debug("all workers are busy")
                break

            job = self.workList.pop()
            self.log.debug("get candidate workers for %s...", job.method)
            candidateWorkers = list(self.workerselector.getCandidateWorkerIds(job.method, self.workers))
            self.log.debug("candidate workers are %r", candidateWorkers)
            for i in candidateWorkers:
                worker = self.workers[i]
                worker.busy = True
                def finished(result, finishedWorker, wId):
                    finishedWorker.busy = False
                    error = None
                    if not isinstance(result, failure.Failure):
                        try:
                            result = pickle.loads(''.join(result))
                        except Exception as e:
                            error = e
                            self.log.exception("Error un-pickling result from worker")

                        # if zenhubworker is about to shutdown, it will wrap the actual result
                        # in a LastCallReturnValue tuple - remove worker from worker list to 
                        # keep from accidentally sending it any more work while it shuts down
                        if isinstance(result, LastCallReturnValue):
                            self.log.debug("worker %s is shutting down" % wId)
                            result = result.returnvalue
                            if finishedWorker in self.workers:
                                self.workers.remove(finishedWorker)

                    else:
                        error = result.getErrorMessage()
                    self.updateStatusAtFinish(wId, error)
                    reactor.callLater(0,self.giveWorkToWorkers)
                    return result

                self.counters['workerItems'] += 1
                self.updateStatusAtStart(i, job)
                try:
                    d2 = worker.callRemote('execute', *job.args)
                    d2.addBoth(finished, worker, i)
                except Exception:
                    self.log.warning("Failed to execute job on zenhub worker")
                    d2 = defer.maybeDeferred(finished, failure.Failure(), worker, i)
                finally:
                    d2.chainDeferred(job.deferred)
                break
            else:
                self.log.debug("no worker available for %s" % job.method)
                #could not complete this job, put it back in the queue once
                #we're finished saturating the workers
                incompleteJobs.append(job)

        for job in reversed(incompleteJobs):
            #could not complete this job, put it back in the queue
            self.workList.push(job)

        if incompleteJobs:
            reactor.callLater(0,self.giveWorkToWorkers)

        if requeue and not self.shutdown:
            reactor.callLater(5,self.giveWorkToWorkers, True)

    def _workerStats(self):
        now = time.time()
        lines = ['Worklist Stats:',
                 '\tEvents:\t%s' % len(self.workList.eventworklist),
                 '\tOther:\t%s' % len(self.workList.otherworklist),
                 '\tApplyDataMaps:\t%s' % len(self.workList.applyworklist),
                 '\tTotal:\t%s' % len(self.workList),
                 'Worker Stats:']
        for wId, worker in enumerate(self.workers):
            stat = self.workTracker.get(wId, None)
            linePattern = '\t%d:%s\t[%s%s]\t%.3fs'
            lines.append(linePattern % (
                wId,
                'Busy' if worker.busy else 'Idle',
                '%s %s' % (stat.status, stat.description) if stat else 'No Stats',
                ' Idle:%.3fs' % stat.previdle if stat and stat.previdle else '',
                now - stat.lastupdate if stat else 0
            ))
        self.log.info('\n'.join(lines))

    def _createWorkerConf(self):
        workerconfigdir = os.path.dirname(self.workerconfig)
        if not os.path.exists(workerconfigdir):
            os.makedirs(workerconfigdir)
        with open(self.workerconfig,'w') as workerfd:
            workerfd.write("hubport %s\n" % self.options.pbport)
            workerfd.write("username %s\n" % self.workerUsername)
            workerfd.write("password %s\n" % self.workerPassword)
            workerfd.write("logseverity %s\n" % self.options.logseverity)
            workerfd.write("zodb-cachesize %s\n" % self.options.zodb_cachesize)
            workerfd.write("calllimit %s\n" % self.options.worker_call_limit)

    def createWorker(self):
        """Start a worker subprocess

        @return: None
        """
        # this probably can't happen, but let's make sure
        if len(self.worker_processes) >= self.options.workers:
            self.log.info("already at maximum number of worker processes, no worker will be created")
            return

        # watch for output, and generally just take notice
        class WorkerRunningProtocol(protocol.ProcessProtocol):

            def __init__(self, parent):
                self._pid = 0
                self.parent = parent
                self.log = parent.log

            @property
            def pid(self):
                return self._pid

            def connectionMade(self):
                self._pid = self.transport.pid
                reactor.callLater(1, self.parent.giveWorkToWorkers)

            def outReceived(self, data):
                self.log.debug("Worker (%d) reports %s" % (self.pid, data.rstrip(),))

            def errReceived(self, data):
                self.log.info("Worker (%d) reports %s" % (self.pid, data.rstrip(),))

            def processEnded(self, reason):
                self.parent.worker_processes.discard(self)
                self.parent.workerprocessmap.pop(self.pid, None)
                self.log.warning("Worker (%d) exited with status: %d (%s)",
                                 self.pid,
                                  reason.value.exitCode,
                                  getExitMessage(reason.value.exitCode))
                # if not shutting down, restart a new worker
                if not self.parent.shutdown:
                    self.log.info("Starting new zenhubworker")
                    self.parent.createWorker()

        if NICE_PATH:
            exe = NICE_PATH
            args = (NICE_PATH, "-n", "%+d" % self.options.hubworker_priority,
                zenPath('bin', 'zenhubworker'), 'run', '-C', self.workerconfig)
        else:
            exe = zenPath('bin', 'zenhubworker')
            args = (exe, 'run', '-C', self.workerconfig)
        self.log.debug("Starting %s", ' '.join(args))
        prot = WorkerRunningProtocol(self)
        proc = reactor.spawnProcess(prot, exe, args, os.environ)
        self.workerprocessmap[proc.pid] = proc
        self.worker_processes.add(prot)

    def heartbeat(self):
        """
        Since we don't do anything on a regular basis, just
        push heartbeats regularly.

        @return: None
        """
        seconds = 30
        evt = EventHeartbeat(self.options.monitor, self.name, 3*seconds)
        self.zem.sendEvent(evt)
        self.niceDoggie(seconds)
        reactor.callLater(seconds, self.heartbeat)
        r = self.rrdStats
        totalTime = sum(s.callTime for s in self.services.values())
        events = r.counter('totalTime', seconds, int(self.totalTime * 1000))
        events += r.counter('totalEvents', seconds, self.totalEvents)
        events += r.gauge('services', seconds, len(self.services))
        events += r.counter('totalCallTime', seconds, totalTime)
        events += r.gauge('workListLength', seconds, len(self.workList))
        for name, value in self.counters.items():
            events += r.counter(name, seconds, value)
        self.zem.sendEvents(events)

        # persist counters values
        self.saveCounters()
        try:
            hbcheck = IHubHeartBeatCheck(self)
            hbcheck.check()
        except:
            self.log.exception("Error processing heartbeat hook")

    def saveCounters(self):
        atomicWrite(
            zenPath('var/zenhub_counters.pickle'),
            pickle.dumps(self.counters),
            raiseException=False,
        )

    def loadCounters(self):
        try:
            self.counters = pickle.load(open(zenPath('var/zenhub_counters.pickle')))
        except Exception:
            pass

    def _sendEmail(self, subject, message):
        if self.options.emailTo:
            recips = self.options.emailTo
            email = MIMEText(message)
            email['Subject'] = subject
            email['From'] = self.dmd.getEmailFrom()
            email['To'] = recips

            result, errorMsg = Utils.sendEmail(email, self.dmd.smtpHost,
            self.dmd.smtpPort, self.dmd.smtpUseTLS, self.dmd.smtpUser,
            self.dmd.smtpPass)
            if result:
                self.log.info("Email sent: %s to %s", subject, recips)
            else:
                self.log.exception("Error sending email: %s to ", subject, recips)
        else:
            self.log.info("Recipients not set; not sending email %s", subject)

    @defer.inlineCallbacks
    def _checkEventThreshold(self):
        result = (EVENT_FLOW_NORMAL, 'unknown', 'unknown')
        queue_size_provider = getUtility(IQueueSizeProvider)
        queues_size =  yield queue_size_provider.getQueuesSize()
        rawSize = queues_size.get('zenoss.queues.zep.rawevents', -1)
        zepSize = queues_size.get('zenoss.queues.zep.zenevents', -1)
        errors = queues_size.get('stderr', '')
        if errors and rawSize==-1 and zepSize==-1:
            self.log.warn("Could not retrieve queues size for event pause control flow.")
            self.log.warn("Error retrieving queues size. {0}".format(errors.rstrip('\n')))

        if  rawSize > getattr(self.dmd, "rawqueuelimit", 1000000) or zepSize > getattr(self.dmd, "zenqueuelimit", 1000000):
            result = (EVENT_FLOW_PAUSE, rawSize, zepSize)
        elif rawSize > getattr(self.dmd, "rawqueuethrottle", 750000) or zepSize > getattr(self.dmd, "zenqueuethrottle", 750000):
            result = (EVENT_FLOW_THROTTLE, rawSize, zepSize)
        else:
            result = (EVENT_FLOW_NORMAL, rawSize, zepSize)
        defer.returnValue(result)

    @defer.inlineCallbacks
    def _checkEventFlow(self):
        try:
            eventFlow, rawsize, zepsize = yield self._checkEventThreshold()
            if self._eventFlow != eventFlow:
                prev = EVENT_FLOWS_MAP[self._eventFlow]
                curr = EVENT_FLOWS_MAP[eventFlow]
                msg = "Changing Event flow from %s to %s" % (prev, curr)
                self.log.info(msg)
                subject = msg
                body = "%s; raw event queue size is %s, zep event queue is %s." % (msg, rawsize, zepsize)
                reactor.callLater(0, self._sendEmail, subject, body )

            for key, svc in self.services.items():
                if key[0] == 'EventService':
                    self.log.debug("Sending eventflow {0} on {1}".format(EVENT_FLOWS_MAP[eventFlow], key[1]))
                    yield svc.setEventFlow(eventFlow)

            self._eventFlow = eventFlow
            self.log.debug("Event flow in state is {0}".format(EVENT_FLOWS_MAP[eventFlow]))
            self.log.debug("Event flow queue sizes (raw, {0}) (zep, {1})".format(rawsize, zepsize))
        except Exception:
            self.log.exception("Error in event flow loop")
        finally:
            reactor.callLater(self.options.eventFlowCheck, self._checkEventFlow)

    def main(self):
        """
        Start the main event loop.
        """
        if self.options.cycle:
            reactor.callLater(0, self.heartbeat)
        if self.options.eventFlowCheck:
            reactor.callLater(0, self._checkEventFlow)
        reactor.run()
        self.shutdown = True
        self.log.debug("Killing workers")
        for proc in self.workerprocessmap.itervalues():
            try:
                proc.signalProcess('KILL')
                self.log.debug("Killed worker %s", proc)
            except ProcessExitedAlready:
                pass
            except Exception:
                pass
        workerconfig = getattr(self,'workerconfig', None)
        if workerconfig and os.path.exists(workerconfig):
            os.unlink(self.workerconfig)
        getUtility(IEventPublisher).close()

    def buildOptions(self):
        """
        Adds our command line options to ZCmdBase command line options.
        """
        ZCmdBase.buildOptions(self)
        self.parser.add_option('--xmlrpcport', '-x', dest='xmlrpcport',
            type='int', default=XML_RPC_PORT,
            help='Port to use for XML-based Remote Procedure Calls (RPC)')
        self.parser.add_option('--pbport', dest='pbport',
            type='int', default=PB_PORT,
            help="Port to use for Twisted's pb service")
        self.parser.add_option('--passwd', dest='passwordfile',
            type='string', default=zenPath('etc','hubpasswd'),
            help='File where passwords are stored')
        self.parser.add_option('--monitor', dest='monitor',
            default='localhost',
            help='Name of the distributed monitor this hub runs on')
        self.parser.add_option('--workers', dest='workers',
            type='int', default=2,
            help="Number of worker instances to handle requests")
        self.parser.add_option('--hubworker-priority', type='int', default=5,
            help="Relative process priority for hub workers (%default)")
        self.parser.add_option('--prioritize', dest='prioritize',
            action='store_true', default=False,
            help="Run higher priority jobs before lower priority ones")
        self.parser.add_option('--anyworker', dest='anyworker',
            action='store_true', default=False,
            help='Allow any priority job to run on any worker')
        self.parser.add_option('--no-graph-proxy', dest='graph_proxy',
            action='store_false', default=True,
            help="Don't listen to proxy graph requests to zenrender")
        self.parser.add_option('--workers-reserved-for-events', dest='workersReservedForEvents',
            type='int', default=1,
            help="Number of worker instances to reserve for handling events")
        self.parser.add_option('--worker-call-limit', dest='worker_call_limit',
            type='int', default=200,
            help="Maximum number of remote calls a worker can run before restarting")
        self.parser.add_option('--invalidation-poll-interval', 
            type='int', default=30,
            help="Interval at which to poll invalidations (default: %default)")
        self.parser.add_option('--event-flow-check', dest='eventFlowCheck',
            type='int', default=0,
            help="Interval at which to check event flow (default: %default, disabled)")
        self.parser.add_option("--email-to", dest="emailTo",
            default=None, type='str',
            help="email address to notify of event flow changes")
            
        notify(ParserReadyForOptionsEvent(self.parser))

class DefaultConfProvider(object):
    implements(IHubConfProvider)
    adapts(ZenHub)

    def __init__(self, zenhub):
        self._zenhub = zenhub

    def getHubConf(self):
        zenhub = self._zenhub
        return zenhub.dmd.Monitors.Performance._getOb(zenhub.options.monitor, None)

class DefaultHubHeartBeatCheck(object):
    implements(IHubHeartBeatCheck)
    adapts(ZenHub)

    def __init__(self, zenhub):
        self._zenhub = zenhub

    def check(self):
        pass

class QueueSizeProvider(object):
    implements(IQueueSizeProvider)

    def __init__(self):
        self._queue_names = ['zenoss.queues.zep.rawevents', 'zenoss.queues.zep.zenevents']
        self._queues_size = {}
        for queue in self._queue_names:
            self._queues_size[queue] = 0

    def getQueuesSize(self):
        return self._queues_size

if __name__ == '__main__':
    from Products.ZenHub.zenhub import ZenHub
    z = ZenHub()

    # during startup, restore performance counters
    z.loadCounters()

    z.main()

    # during shutdown, attempt to save our performance counters
    z.saveCounters()
