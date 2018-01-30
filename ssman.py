#!/usr/bin/python
import sys
import socket
import getopt
import os
import json
import time
import signal

class Usage(Exception):
    '''Operation Usage : [opt] [arg]
    \r-a                    : create ss-server on port [arg]. '--password' must be specified.
    \r-r                    : remove ss-server on port [arg].
    \r-l                    : list ports from ss-manager and show each data usage.
    \r--manager-address     : ss-manager address, default is "/tmp/manager.sock".
    \r--socket-address      : default is "/tmp/client.sock".
    \r--add-json            : create ss-servers by json file with formart: {"add":[{"server_port":8900,"password":"password"},...]}.
    \r-h,--help             : show help information.'''
    def __init__(self, msg):
        self.msg = msg

class u_socket:
    def __init__(self, manAddr, sockAddr):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        self.managerAddr = manAddr
        self.socketAddr = sockAddr

    def connect(self):
        if os.path.exists(self.socketAddr):
            os.unlink(self.socketAddr)
        self.sock.bind(self.socketAddr)
        self.sock.connect(self.managerAddr)

    def cmd(self, sendMsg, recvSize = 1024):
        self.sock.send(sendMsg)
        return self.sock.recv(recvSize)

def keyTerminate(a, b):
    print "\033[?25h"
    sys.exit(0)

def createCMD(opt, **args):
    if opt == "add":
        return "add: {\"server_port\":%d,\"password\":\"%s\"}"%(args["server_port"],args["password"])
    elif opt == "remove":
        return "remove: {\"server_port\":%d}"%args["server_port"]
    elif opt == "ping":
        return "ping"

def showUsage(json_data):
    print "***Data Usage***"
    print " Port\tData(MB)"
    for server in json_data:
        mb = (json_data[server]/1024.0)/1024.0
        print " %s\t%.2f"%(server, mb)

def portMonitor(u_socket):
    print "Start monitor operation... You can quit with CONTROL-C"
    print "\033[?25l\t******Port Monitor******"
    print "\tPort\tSPD(KB/s)\tDATA(MB)"
    last_linenum = 0
    sample_time = 5
    last_msg = None
    while True:
        msg = json.loads(u_socket.cmd(createCMD("ping"))[6:])
        if last_linenum:
            print "\033[%dA"%last_linenum,
            last_linenum=0
        for port in msg:
            mb = (msg[port]/1024.0)/1024.0
            spd = 0
            if last_msg:
                spd = ((msg[port]-last_msg[port])/1024.0)/sample_time
            print "\t%s\t%.2f\t\t%.2f"%(port, spd, mb)
            last_linenum += 1
        last_msg = msg
        time.sleep(sample_time)
    

def processJson(opt, u_socket, json_data):
    if opt == "add":
        cmdGroup = json_data["add"]
        total = 0
        success = 0
        for cmd in cmdGroup:
            ack = u_socket.cmd(createCMD("add", server_port = cmd["server_port"], password = cmd["password"]))
            total += 1
            if ack == "ok":
                success += 1
        print "'--add-json' result: total add: %d, success %d."%(total,success)

def main(argv=None):
    
    
    signal.signal(signal.SIGINT, keyTerminate)

    if argv is None:
        argv = sys.argv
    
    ERR         = "\033[1;31mERR:\033[0m"
    WARN        = "\033[1;33mWARN:\033[0m"

    cmd_add     = False
    cmd_ping    = False
    cmd_remove  = False
    cmd_addjson = False
    cmd_monitor = False
    cmd_service = False

    password    = None
    mangerAddr  = "/tmp/manager.sock"
    socketAddr  = "/tmp/client.sock"
    pidPath     = ""

    try:
        try:
            opts, args = getopt.getopt(argv[1:], "a:f:hlmr:", ["password=", "add-json=", "manager-address=", "socket-address=", "help"])
        except getopt.error, msg:
            raise Usage(msg)
        
        if len(opts)== 0:
            raise Usage("need operation.")

        for opt, arg in opts:
            if opt == '-a':
                cmd_add = True
                try:
                    port_add = int(arg)
                except ValueError, msg:
                    raise Usage(msg)
            elif opt == '-r':
                cmd_remove = True
                try:
                    port_remove = int(arg)
                except ValueError, msg:
                    raise Usage(msg)
            elif opt == '-l':
                cmd_ping = True
            elif opt == '--password':
                password = arg
            elif opt == '--add-json':
                cmd_addjson = True
                json_path = arg
            elif opt == '--manager-address':
                managerAddr = arg
            elif opt == '--socket-address':
                socketAddr = arg
            elif opt == '-m':
                cmd_monitor = True
            elif opt in ('-h', '--help'):
                print Usage.__doc__
            elif opt in ('-f'):
                cmd_service = True
                pidPath = arg

        if cmd_add and (not password):
            raise Usage("opt '-a' need '--password'")
        if cmd_monitor and cmd_service:
            raise Usage("can not use opt '-m' and '-f' at the same time")

    except Usage, err:
        print >>sys.stderr, ERR, err.msg
        print >>sys.stderr, err.__doc__
        return 1
    if not( cmd_add or cmd_ping or cmd_remove or cmd_addjson or cmd_monitor ):
        return 0

    try:
        try:
            sock = u_socket(mangerAddr, socketAddr)
            sock.connect()
        except socket.error, msg:
            raise Usage(msg)
        print "\033[1;32mConnected Success.\033[0m"

        '''
        ****** Operation Start ******
        '''

        try:
            if cmd_add == True:
                ack = sock.cmd(createCMD("add", server_port = port_add, password = password))
                print "add port: %d %s"%(port_add,ack)
        except Exception, msg:
            print >>sys.stderr, WARN, msg, "opt '-a' failed."

        try:
            if cmd_remove == True:
                ack = sock.cmd(createCMD("remove", server_port = port_remove))
                print "remove port: %d %s"%(port_remove,ack)
        except Exception, msg:
            print >>sys.stderr, WARN, msg, "opt '-r' failed."

        try:
            if cmd_addjson == True:
                jsonMsg = json.load(open(json_path,'r'))
                processJson("add", sock, jsonMsg)
        except Exception, msg:
            print >>sys.stderr, WARN, msg, "opt '--add-json' failed."

        try:
            if cmd_ping == True:
                recvMsg = sock.cmd(createCMD("ping"))
                recvMsg = json.loads(recvMsg[6:])
                showUsage(recvMsg)
        except Exception, msg:
            print >>sys.stderr, WARN, msg, "opt '-l' failed."

        if cmd_monitor == True:
            portMonitor(sock)

        if cmd_service == True:

        '''
        ****** Operation End ******
        '''

    except Usage, err:
        print >>sys.stderr, ERR, err.msg
        return 2

if __name__ == '__main__':
    sys.exit(main())
