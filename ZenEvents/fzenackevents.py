#!/usr/bin/env python
##############################################################################
# 
# Copyright (C) Zenoss, Inc. 2014, all rights reserved.
# 
# This content is made available according to terms specified in
# License.zenoss under the directory where your Zenoss product is installed.
# 
##############################################################################


import urllib
import urllib2
import json
import socket
import ssl
import httplib
import argparse
import ConfigParser
from os import environ
import logging
import logging.handlers
log = logging.getLogger('zen.zenackevents')
from subprocess import call
import base64


class ZenJsonClientError(Exception):
    pass


class Response(object):

    def __init__(self, action, method, result, tid, type_, uuid):
        self.action = action
        self.method = method
        self.result = result
        self.tid = tid
        self.type_ = type_
        self.uuid = uuid

    def __repr__(self):
        from pprint import pformat
        return "<zenjsonclient.Response(action={action},\n" \
               "                        method={method},\n" \
               "                        tid={tid},\n" \
               "                        type_={type_},\n" \
               "                        uuid={uuid},\n" \
               "                        result=\n{result},\n" \
               ")>".format(action=self.action,
                           method=self.method,
                           tid=self.tid,
                           type_=self.type_,
                           uuid=self.uuid,
                           result=pformat(self.result),)


class Client(object):

    def __init__(self, protocol, host, port, username, password):
        self.protocol = protocol
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.base_url = "{0}://{1}:{2}".format(self.protocol, self.host, self.port)
        self.opener = None

    def open(self, url, data):
        try:
            return self.opener.open(url, data)
        except urllib2.URLError as e:
            self.opener = None
            if e.args:
                embedded_error = e.args[0]
                if isinstance(embedded_error, ssl.SSLError):
                    er = str(embedded_error).split(":")[-1].strip()
                    log.error(er)
                    raise ZenJsonClientError(er)
                elif isinstance(embedded_error, (socket.gaierror, socket.error)):
                    log.error(str(embedded_error.args[1]))
                    raise ZenJsonClientError(str(embedded_error.args[1]))
                else:
                    log.error(str(embedded_error))
                    raise ZenJsonClientError(str(embedded_error))
            else:
                log.error(str(e))
                raise ZenJsonClientError(str(e))
        except httplib.InvalidURL as e:
            self.opener = None
            log.error(str(e))
            raise ZenJsonClientError(str(e))

    def login(self):
        self.opener = urllib2.build_opener(urllib2.HTTPCookieProcessor())
        loginParams = urllib.urlencode(dict(__ac_name=self.username,
                                            __ac_password=self.password,
                                            submitted="true",
                                            came_from="{0}/zport/dmd/".format(self.base_url)))
        url = "{0}/zport/acl_users/cookieAuthHelper/login".format(self.base_url)
        self.open(url, loginParams)
        self.tid = 1

    def make_request(self, url_path, action, method, data=[]):
        if self.opener is None:
            self.login()
            assert self.opener is not None
            log.debug('logged in successfuly')
        req = urllib2.Request("{0}/zport/dmd/{1}".format(self.base_url, url_path))
        req.add_header('Content-type', 'application/json; charset=utf-8')
        req_data = json.dumps([dict(action=action, method=method,
                              data=data, type='rpc', tid=self.tid,)])
        resp = self.open(req, req_data)
        json_str = resp.read()
        try:
            json_obj = json.loads(json_str)

        except ValueError:
            self.opener = None
            er = "Could not authenticate to Zenoss instance or wrong port."
            log.error(er)
            raise ZenJsonClientError(er)

        self.tid += 1
        return json_obj


class EventsRouter(object):

    def __init__(self, client):
        self.client = client
        self.url_path = "evconsole_router"

    def changeState(self, evids, state):
        data = {'evids': evids,
                'params': None,
                'uid': None,
                'limit': None,
                'excludeIds': None,
                'asof': None}
        actions = ["reopen", "acknowledge"]
        resp = self.client.make_request(self.url_path,
                                        "EventsRouter", actions[state], [data])
        return resp.get('result').get('data').get('updated') \
            and resp.get('result').get('success')


def main():
    zPath = environ.get("ZENHOME") or "/opt/zenoss"
    cPath = zPath + "/etc/zenackevents.conf"

    logFile = zPath + '/log/zenackevents.log'
    log.setLevel(logging.INFO)
    handler = logging.handlers.RotatingFileHandler(
        logFile, maxBytes=5*2**20, backupCount=3)
    handler.setLevel(logging.INFO)
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    log.addHandler(handler)
    consoleHandler = logging.StreamHandler()
    log.addHandler(consoleHandler)

    conf_parser = argparse.ArgumentParser(
        description="Events acknowledgement command line tool", add_help=False)
    conf_parser.add_argument("-c", "--conf_file", default=cPath,
                             help="Specify config file")
    args, remaining_argv = conf_parser.parse_known_args()

    defaults = {
        "state": 1,
        "userid": "admin",
        "obfuscated": "",
        "host": "localhost",
        "port": 8080,
        "protocol": "http"}

    if args.conf_file:
        config = ConfigParser.SafeConfigParser()
        if config.read([args.conf_file]) != []:
            defaults.update(dict(config.items("Zenackevents")))
        else:
            log.warn("Could not read config file, should be at %s", args.conf_file)
    parser = argparse.ArgumentParser(
        parents=[conf_parser],
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        prog='zenackevents',
        usage='%(prog)s [options]')
    parser.set_defaults(**defaults)

    parser.add_argument('--evid', '-e', help='event id that is acked')
    parser.add_argument('--state', '-s',
                        help="state to change to, 1 is 'acknowledged', 0 is 'new'",
                        choices=[0, 1], type=int)
    parser.add_argument('--userid', '-u', help='ZEP username')
    parser.add_argument('--password', '-p', help='ZEP password')
    parser.add_argument('--host', '-H', help='ZEP server hostname')
    parser.add_argument('--port', '-P', help='ZEP server port', type=int)
    parser.add_argument('--protocol', '-r',
                        help='ZEP protocol', choices=['http', 'https'])
    parser.add_argument('--setpassword', '-S',
                        help='write password to config file', metavar='PASSWORD')

    args, unknown = parser.parse_known_args()
    password = args.password or base64.b64decode(defaults['obfuscated'])
    if not args.evid:
        if args.setpassword:
            if 'Zenackevents' not in config.sections():
                config.add_section('Zenackevents')
            config.set('Zenackevents', 'obfuscated', base64.b64encode(args.setpassword))

            with open(args.conf_file, 'wb') as configfile:
                config.write(configfile)
            log.info("Obfuscated password successfuly written to %s", args.conf_file)
            return 0
        else:
            log.error("Please provide event ID via argument --evid/-e")
            parser.print_help()
            return 1

    # no password is set! falling back to old slow method
    if not password:
        log.info("Writing ZEP password to config file with " \
            "--setpassword will greatly improve zenackevents performance")
        oldZenackevents = (zPath + '/bin/python',
                           zPath + '/Products/ZenEvents/zenackevents.py',
                           '--evid=' + args.evid,
                           '--state=' + str(args.state),
                           '--userid=' + args.userid)
        return call(oldZenackevents)

    client = Client(args.protocol, args.host, args.port, args.userid, password)
    er = EventsRouter(client)
    if er.changeState([args.evid], args.state):
        log.info("Successfuly set event %s state to %d", args.evid, args.state)
        return 0
    else:
        log.error("Could not set event %s state to %d", args.evid, args.state)
        return 1


if __name__ == '__main__':
    exit(main())
