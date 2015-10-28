##############################################################################
# 
# Copyright (C) Zenoss, Inc. 2014, all rights reserved.
# 
# This content is made available according to terms specified in
# License.zenoss under the directory where your Zenoss product is installed.
# 
##############################################################################

import Globals

from ZopeRequestLogger import ZopeRequestLogger

import subprocess
import re
import time
import datetime
import os
import sys
import redis
import argparse
import json

SCRIPT_VERSION = '1.1.0'

'''------------------------ VERSION SUMMARY --------------------------------
   1.0.0  pending zope calls detected parsing start/end traces from log file
   1.1.0  pending zope calls detected using Redis. output less verbose
   -------------------------------------------------------------------------'''

REDIS_URL = ZopeRequestLogger.get_redis_url()

def execute_command(command):
    """
    Params: command to execute
    Return: tuple containing the stout and stderr of the command execution
    """
    proc = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = proc.communicate()
    return (stdout, stderr)

class ZopeInfoRetriever(object):

	COMMAND = "zenwebserver status -v"
	STATUS_REGEX = '(?P<name>.*) status (\s+)\[(?P<status>.+)\]'
	PID_PORT_REGEX = 'Running \(pid (?P<pid>\d+)\), Listening \(port (?P<port>.*)\)'
	def __init__(self):
		pass

	def _execute_regex(self, expr, line):
		results = {}
		regex = re.compile(expr)
		match = regex.search(line)
		if match:
			results = match.groupdict()
		return results

	def _match_status_line(self, line):
		return self._execute_regex(ZopeInfoRetriever.STATUS_REGEX, line)

	def _match_pid_line(self, line):
		return self._execute_regex(ZopeInfoRetriever.PID_PORT_REGEX, line)

	def _parse_command_output(self, output):
		zopes = []
		zope = None
		for line in output.split('\n'):
			status_line_results = self._match_status_line(line)
			if status_line_results:
				zope = ZopeInfo()
				zope.name = status_line_results.get('name', '')
				zope.status = status_line_results.get('status', '')
				if 'UP' in zope.status:
					zope.running = True
				else:
					zopes.append(zope)
					zope = None
			else:
				pid_line_results = self._match_pid_line(line)
				if pid_line_results:
					zope.pid = pid_line_results.get('pid', '')
					zope.port = pid_line_results.get('port', '')
					zope.id = zope.port
					zopes.append(zope)
		return zopes

	def getZopesInfo(self):
		""" """
		zopes = []
		output, stderr = execute_command(ZopeInfoRetriever.COMMAND)
		if len(stderr) > 0:
			print 'Error retrieving zopes information'
		else:
			zopes = self._parse_command_output(output)
		return zopes

class ProcessInfoRetriever(object):

	COMMAND = 'ps -p {0} -o %cpu,%mem,etime,cmd | tail -n +2'

	def __init__(self):
		pass

	def _parse_elapsed_time(self, etime):
		'''
		etime format: days-HH:MM:SS
		'''
		if not etime:
			return ''

		parsing = etime.split('-')
		days = ''
		if len(parsing) > 1:
			days = parsing[0]
			remaining = parsing[1]
		else:
			remaining = parsing[0]

		time = remaining.split(':')
		time = time[::-1]
		seconds = 0
		if days:
			seconds = 24 * 60 * 60
		for index, element in enumerate(time):
			seconds = seconds + pow(60, index)*int(element)
		return seconds


	def get_process_info(self, pid):
		info = {}
		command = ProcessInfoRetriever.COMMAND.format(pid)
		output, stderr = execute_command(command)
		if len(stderr) == 0 and len(output) > 0:
			data = output.split()
			if len(data) >= 3:
				info['pid'] = pid
				info['cpu'] = data[0]
				info['mem'] = data[1]
				info['etime'] = data[2]
				info['seconds_running'] = self._parse_elapsed_time(data[2])
				info['cmd'] = ' '.join(data[3:])
		return info

def get_redis_client():
	redis_client = ZopeRequestLogger.create_redis_client(REDIS_URL)
	if redis_client is None:
		msg = 'ERROR connecting to redis. redis URL: {0}'.format(REDIS_URL)
		print msg
		print 'Please check the redis-url value in global.conf'
		sys.exit(1)
	return redis_client

class ZopeAssignmentDataRetriever(object):

	def __init__(self):
		self._redis_client = get_redis_client()

	def get_pending_assignments(self):
		pattern = '{0}*'.format(ZopeRequestLogger.REDIS_KEY_PATTERN)
		keys = self._redis_client.keys(pattern)
		assignments = []
		for key in keys:
			value = self._redis_client.get(key)
			assignments.append(json.loads(value))
		return assignments

#------------------------------------------------------------------------------------------------

class ZopeInfo(object):

	def __init__(self):
		self.id = ''
		self.name = ''
		self.pid = ''
		self.status = ''
		self.running = False
		self.port = ''
		#Zope process info
		self.cpu = '-1'
		self.mem = '-1'
		self.cmd = ''
		self.etime = ''
		self.seconds_running = 0
		#Zope Assigments
		self.assignments = []

	def add_assignment(self, assignment):
		self.assignments.append(assignment)

	def set_process_info(self, data):
		self.cpu = data.get('cpu', '')
		self.mem = data.get('mem', '')
		self.etime = data.get('etime', 0)
		self.seconds_running = data.get('seconds_running', 0)
		self.cmd = data.get('cmd', '')

	def __str__(self):
		if self.running:
			return 'Zope: port [{0}] / pid [{1}] / %cpu [{2}] / %mem [{3}] / etime [{4}]'.format(self.port, self.pid, self.cpu, self.mem, self.etime)
		else:
			return 'Zope: port [{0}]'.format(self.port)

class ZopeAssignment(object):

	def __init__(self, data):
		self.user_name = data.get('user_name', '')
		self.trace_type = data.get('trace_type', '')
		self.start_time = data.get('start_time', '')
		self.server_name = data.get('server_name', '')
		self.server_port = data.get('server_port', '')
		self.path_info = data.get('path_info', '')
		self.http_method = data.get('http_method', '')
		self.client = data.get('client', '')
		self.http_host = data.get('http_host', '')
		self.action_and_method = data.get('action_and_method', '')
		self.forwarded_for = data.get('xff', '')
		self.body = data.get('body', {})
		self.zope_id = self.server_port

	def __str__(self):
		t = datetime.datetime.fromtimestamp(float(self.start_time))
		#format = "%Y-%m-%d %H:%M:%S"
		#running_since = t.strftime(format)
		ass_str = [ ]
		time_info = 'Request started {0} seconds ago'.format(str(datetime.datetime.now() - t))
		ass_str.append('{0}  /  User: {1}  /  Client: {2} '.format(time_info, self.user_name, self.client))
		ass_str.append('Path: {0}  /  Action/Method: {1}'.format(self.path_info, self.action_and_method))
		if self.forwarded_for:
			ass_str.append('Forwarded for: {0}'.format(self.forwarded_for))
		return '\n\t'.join(ass_str)

class ZopesManager(object):

	def __init__(self, cli_options):
		self.zopes = {} # dict {zope_id: ZopeInfo}
		self.cli_options = cli_options

	def _load_zopes_assignments(self):
		'''
		retrieved the pending zopes assignments from redis
		'''
		assignment_retreiver = ZopeAssignmentDataRetriever()
		assingments_data = assignment_retreiver.get_pending_assignments()
		assignments = {}
		for data in assingments_data:
			new_assignment = ZopeAssignment(data)
			zope_assignments = assignments.get(new_assignment.zope_id, [])
			zope_assignments.append(new_assignment)
			assignments[new_assignment.zope_id] = zope_assignments
		return assignments

	def _get_running_zopes(self):
		''' Loads available zopes by executing zenwebserver status -v '''
		running_zopes = {}

		zope_retriever = ZopeInfoRetriever()
		zope_list = zope_retriever.getZopesInfo()
		process_info_retreiver = ProcessInfoRetriever()
		for zope in zope_list:
			if zope.id and 'Load balancer' not in zope.name and zope.running:
				process_info = process_info_retreiver.get_process_info(zope.pid)
				zope.set_process_info(process_info)
				running_zopes[zope.id] = zope
		return running_zopes

	def _get_zope_for_assignment(self, assignment):
		assignment_for = None
		for zope_id in self.zopes.keys():
			zope = self.zopes.get(zope_id)
			if zope and assignment.zope_id in zope_id:
				assignment_for = zope
				break
		return assignment_for

	def _process_assigments(self, assigments, process_all=True):
		'''
		all = True  : all assigments are processed
		all = False : only assignments processed by a zope that is 
		              running and assignment.start_time > zope.start_time
		'''
		for zope_id, assignments in assigments.iteritems():
			if not zope_id: continue
			for assignment in assignments:
				if process_all:
					if zope_id not in self.zopes.keys():
						zope = ZopeInfo()
						zope.zope_id = zope_id
						zope.port = assignment.server_port
						self.zopes[zope_id] = zope
					self.zopes[zope_id].add_assignment(assignment)
				else:
					zope = self._get_zope_for_assignment(assignment)
					if zope and zope.seconds_running > 0:
						now_timestamp = datetime.datetime.now()
						ass_timestamp = datetime.datetime.fromtimestamp(float(assignment.start_time))
						assignment_running_for = (now_timestamp - ass_timestamp).total_seconds()
						if assignment_running_for > 5  and assignment_running_for < float(zope.seconds_running):
							zope.add_assignment(assignment)

	def print_zopes_stats(self):
		os.system('clear')
		time.sleep(0.05)  # make refresh noticeable

		if len(self.zopes.keys()) == 0:
			if self.cli_options.get('running_zopes'):
				print '\nCould not find any running zopes...'
			else:
				print '\nCould not find any pending zope assignments...'
		else:
			first = True
			for zope_id in sorted(self.zopes.keys()):
				zope = self.zopes.get(zope_id)
				zope_str = str(zope)
				if first:
					print '-'*len(zope_str)
					first = False
				print '{0}'.format(zope_str)
				for assignment in zope.assignments:
					print '     {0}'.format(assignment)
				print '-'*len(zope_str)

	def check_running_zopes_assignments(self):
		self.zopes = {}
		assignments = self._load_zopes_assignments()
		self.zopes = self._get_running_zopes()
		self._process_assigments(assignments, process_all=False)
		self.print_zopes_stats()

	def check_all_zopes_assignments(self):
		self.zopes = {} # Zopes will be populated when assignments are processed
		assignments = self._load_zopes_assignments()
		self._process_assigments(assignments, process_all=True)
		self.print_zopes_stats()

def parse_options():
    """Defines command-line options for script """
    parser = argparse.ArgumentParser(version=SCRIPT_VERSION,
                                     description="Checks for unfinished Zope requests.")
    parser.add_argument("-r", "--running_zopes", action="store_true", default=False,
                        help="Displays non finished requests for zopes that are currently running")
    parser.add_argument("-c", "--cycle", action="store_true", default=False,
                        help="performs the check periodically and only checks for requests assigned to zopes that are currently running")
    parser.add_argument("-freq", "--freq", action="store", default=5, type=int,
                        help="frecuency at which the check is performed (in seconds)")
    parser.add_argument("-clear", "--clear_redis", action="store_true", default=False,
                        help="Clears all pending zope requests from redis")
    parser.add_argument("-show_details", "--show_details", action="store_true", default=False,
                        help="Shows detailed information about the not finished requests")
    return vars(parser.parse_args())

def clear_redis():
	redis_client = get_redis_client()
	pattern = '{0}*'.format(ZopeRequestLogger.REDIS_KEY_PATTERN)
	keys = redis_client.keys(pattern)
	redis_client.delete(*keys)

def print_all_not_finished_assigments():
	redis_client = get_redis_client()
	pattern = '{0}*'.format(ZopeRequestLogger.REDIS_KEY_PATTERN)
	keys = redis_client.keys(pattern)
	print '-'*50
	print 'Found {0} unfinished requests'.format(len(keys))
	print '-'*50
	if keys:
		values = redis_client.mget(keys)
		for value in values:
			print json.loads(value)
			print '-'*50

def main():
	""" """
	cli_options = parse_options()

	if cli_options.get('clear_redis'):
		clear_redis()
		print "Pending requests cleared from redis"
		sys.exit(0)

	if cli_options.get('show_details'):
		print_all_not_finished_assigments()
		sys.exit(0)

	os.system('clear')
	while True:
		zopes_manager = ZopesManager(cli_options)
		if cli_options.get('running_zopes'):
			zopes_manager.check_running_zopes_assignments()
		else:
			zopes_manager.check_all_zopes_assignments()
		if not cli_options.get('cycle'):
			break;
		print ('\nSleeping for {0} seconds'.format(cli_options.get('freq')))
		time.sleep(cli_options.get('freq'))

if __name__ == "__main__":
	main()

