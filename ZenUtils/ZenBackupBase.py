#! /usr/bin/env python
##############################################################################
#
# Copyright (C) Zenoss, Inc. 2007, 2009, 2013 all rights reserved.
#
# This content is made available according to terms specified in
# License.zenoss under the directory where your Zenoss product is installed.
#
##############################################################################


__doc__ = '''ZenBackupBase

Common code for zenbackup.py and zenrestore.py
'''
import tempfile
import logging
from subprocess import Popen, PIPE

from zope.component import getUtility
from Products.ZenUtils.ZodbFactory import IZodbFactoryLookup
from Products.ZenUtils.GlobalConfig import globalConfToDict
from CmdBase import CmdBase


BACKUP_DIR = 'zenbackup'
CONFIG_FILE = 'backup.settings'
CONFIG_SECTION = 'zenbackup'

log = logging.getLogger("zenbackupbase")


def getPassArg(options, optname='zodb_password'):
    """
    Return string to be used as the -p (including the "-p")
    to MySQL commands.

    @return: password and flag
    @rtype: list
    """
    password = getattr(options, optname, None)
    if not password:
        return []
    return ['-p%s' % password]


def getEnterpriseToolPath(options):
    """

    @param options:
    @return:
    """
    return options.enterpriseToolPath


def getMySQLCommand(host, port, user, passwd, compress=False, socket=None):
    """Build and return the mysql command.
    """
    mysql_cmd = ['mysql', '-u%s' % user]
    mysql_cmd.extend(passwd)
    if host and host != 'localhost':
        mysql_cmd.extend(['--host', host])
        if compress:
            mysql_cmd.append('--compress')
    if port and str(port) != '3306':
        mysql_cmd.extend(['--port', str(port)])
    if socket:
        mysql_cmd.extend(['--socket', socket])
    mysql_cmd.extend(["-B", "--skip-column-names"])
    return mysql_cmd


def is_db_remote(host):
    import socket

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect((host, 22))
    isRemote = s.getpeername()[0] != s.getsockname()[0]
    s.close()
    return isRemote


def runCommand(cmd=[], obfuscated_cmd=None):
    """
    Execute a command and return the results, displaying pre and
    post messages.

    @parameter cmd: command to run
    @type cmd: list
    @return: results of the command (output, warnings, returncode)
    """
    if obfuscated_cmd:
        log.debug(' '.join(obfuscated_cmd))
    else:
        log.debug(' '.join(cmd))
    proc = Popen(cmd, stdout=PIPE, stderr=PIPE)
    output, warnings = proc.communicate()
    if proc.returncode:
        log.warn(warnings)
    log.debug(output or 'No output from command')
    return (output, warnings, proc.returncode)


class ZenBackupBase(CmdBase):
    doesLogging = False

    def __init__(self, noopts=0):
        super(ZenBackupBase, self).__init__(noopts=noopts)

    def msg(self, msg):
        """
        If --verbose then send msg to stdout
        """
        if self.options.verbose:
            print(msg)

    def buildOptions(self):
        """
        Command-line options setup
        """
        CmdBase.buildOptions(self)
        connectionFactory = getUtility(IZodbFactoryLookup).get()
        connectionFactory.buildOptions(self.parser)
        self.parser.add_option('-v', '--verbose',
                               dest="verbose",
                               default=False,
                               action='store_true',
                               help='Send progress messages to stdout.')
        self.parser.add_option('--temp-dir',
                               dest="tempDir",
                               default=None,
                               help='Directory to use for temporary storage.')
        self.parser.add_option('--dont-fetch-args',
                               dest='fetchArgs',
                               default=True,
                               action='store_false',
                               help='By default MySQL connection information'
                                    ' is retrieved from Zenoss if not'
                                    ' specified and if Zenoss is available.'
                                    ' This disables fetching of these values'
                                    ' from Zenoss.')
        self.parser.add_option('--zepdbname',
                               dest='zepdbname',
                               default='zenoss_zep',
                               help='ZEP database name.'
                                    ' By default this will be fetched from Zenoss'
                                    ' unless --dont-fetch-args is set.'),
        self.parser.add_option('--zepdbuser',
                               dest='zepdbuser',
                               default='root',
                               help='ZEP database username.'
                                    ' By default this will be fetched from Zenoss'
                                    ' unless --dont-fetch-args is set.'),
        self.parser.add_option('--zepdbpass',
                               dest='zepdbpass',
                               default='',
                               help='ZEP database password.'
                                    ' By default this will be fetched from Zenoss'
                                    ' unless --dont-fetch-args is set.'),
        self.parser.add_option('--zepdbhost',
                               dest='zepdbhost',
                               default='localhost',
                               help='ZEP database server host.'
                                    ' By default this will be fetched from Zenoss'
                                    ' unless --dont-fetch-args is set.'),
        self.parser.add_option('--zepdbport',
                               dest='zepdbport',
                               default='3306',
                               help='ZEP database server port number.'
                                    ' By default this will be fetched from Zenoss'
                                    ' unless --dont-fetch-args is set.'),
        self.parser.add_option('--compress-transport',
                               dest="compressTransport",
                               default=True,
                               help='Compress transport for MySQL backup/restore.'
                                    ' True by default, set to False to disable over'
                                    ' fast links that do not benefit from compression.')
        self.parser.add_option('--enterprise-tool-path',
                               dest='enterpriseToolPath',
                               default='mysqlbackup',
                               help='Path to the enterprise tool for backup')

    def getTempDir(self):
        """
        Return directory to be used for temporary storage
        during backup or restore.

        @return: directory name
        @rtype: string
        """
        if self.options.tempDir:
            directory = tempfile.mkdtemp('', '', self.options.tempDir)
        else:
            directory = tempfile.mkdtemp()
        return directory

    def readZEPSettings(self):
        """
        Read in and store the ZEP DB configuration options
        to the 'options' object.
        """
        globalSettings = globalConfToDict()
        zepsettings = {
            'zep-admin-user': 'zepdbuser',
            'zep-host': 'zepdbhost',
            'zep-db': 'zepdbname',
            'zep-admin-password': 'zepdbpass',
            'zep-port': 'zepdbport'
        }

        for key in zepsettings:
            if key in globalSettings:
                value = str(globalSettings[key])
                setattr(self.options, zepsettings[key], value)
