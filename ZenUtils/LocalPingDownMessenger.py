import logging 
import datetime
import pickle
from Products.ZenUtils.FileCache import FileCache
from Products.ZenUtils.Utils import zenPath

log = logging.getLogger("zen.LocalPingDownMessenger")

class LocalPingDownMessenger(object):
    def __init__(self,monitor,redis_url=None):
	self._monitor=monitor
	self._pingDownIpSetKeyStr=self._monitor+"_pingDownIpSetKey"
	self._pingDownLastUpdateStr=self._monitor+"_pingDownLastUpdate"
	if redis_url is None:
	    self._setFileCacheAsMessenger()
	else:
	    try:
		import redis
		from Products.ZenUtils.redis import parseRedisUrl
		self.save=redisSave
		from zope import component
		options = component.getUtility(ZenCollector.interfaces.ICollector).options
		# create redis client
		self._client = redis.StrictRedis(redis_url)
	        self._sendMessage = self._sendMessageViaRedis
		self._isIpDown = self._isIpDownRedis
		log.debug("Using redis server to save pingdown data.")
	    except ImportError:
		log.warn("redis Not packaged. Using filecache.")
		self._setFileCacheAsMessenger()
	    
    def _setFileCacheAsMessenger(self):
	self._path=zenPath('var',self._monitor,'zenping','downlist')
	self._sendMessage=self._sendMessageViaFileCache
	self._isIpDown = self._isIpDownFileCache
	log.debug("Using FileCache to save pingdown data.")
	
    def _sendMessageViaRedis(self, downTasks):
	pipe = self._client.pipeline() #pipe allow us to perform bulk operations
	pipe.delete(self._pingDownIpSetKeyStr)
	for ip,value in downTasks.iteritems():
	    pipe.sadd(self._pingDownIpSetKeyStr,ip)
	pipe.set(self_pingDownLostUpdateStr,datetime.datetime.now().isoformat())
	pipe.execute()
	
    def _sendMessageViaFileCache(self,downTasks):
	cache= FileCache(self._path)
	cache.clear()
	cache[self._pingDownLastUpdateStr]=datetime.datetime.now().isoformat()
	for ip,value in downTasks.iteritems():
	    cache[ip]=True

    def setDownIps(self,downTasks):
	"""sends IPdown list to the local persistence storage, it expects downTasks to be a dictionary
	with the keys being the all the ip addresses(in string format)."""
	self._sendMessage(downTasks)

    def _isIpDownRedis(self,ipStr):
	"""Returns true if the ip is marked as down by ping"""
	return self._client.sismember(self._pingDownIpSetKeyStr,ipStr)
	
    def _isIpDownFileCache(self,ipStr):
	cache= FileCache(self._path)
	return ipStr in cache
	
    def isIpDown(self,ipStr):
	"""Returns true if the ip is marked as down by ping"""
	return self._isIpDown(ipStr)
	
    def getAllDownIps(self):
	"""return a tuple of the last pingdown update time and list of down ips"""
	return self._getMessage()