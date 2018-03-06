#!/usr/bin/python
import sys
import getopt
import os
import json
import time
import signal
import socket
import threading
import Queue
from ssutils import ss_database, ssmanErr

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

class pool():
    cursor = -1
    pool_dict={}

    def __init__(self, size, start=0):
        self.start=start
        self.size=size
        self.end=start+size
        for i in range(start,start+size):
            self.pool_dict[i]=0
    
    def set(self, index, val):
        if self.pool_dict.has_key(index):
            self.pool_dict[index]=val

    def get(self):
        if self.cursor == -1:
            self.cursor = self.start
        for i in range(self.cursor, self.end):
            if self.pool_dict[i]==0:
                self.cursor = i
                return self.cursor
        self.cursor = -1
        return self.cursor

    def check(self,index):
        if self.pool_dict.has_key(index):
            return self.pool_dict[index]
        else:
            return -1

class ss_daemon():
    manAddr = "/tmp/manager.sock"
    sockAddr = "/tmp/client.sock"
    dbPath = "/home/tupers/test.db"
    pidPath = "/tmp/ssdaemnon.pid"
    logPath = "/tmp/ssmand.log"
   
    daemon_isRun = True

    cmd_queue = Queue.Queue(5)

    portpool = pool(11,7890)

    def __init__(self, **kwargs):
        self.setOpt(kwargs, "managerAddr", self.manAddr)
        self.setOpt(kwargs, "socketAddr", self.sockAddr)
        self.setOpt(kwargs, "dbPath", self.dbPath)
        self.setOpt(kwargs, "pidPath", self.pidPath)
        self.setOpt(kwargs, "logPath", self.logPath)

    def setOpt(self, args, argname, opt):
        if argname in args:
            opt = args[argname]

    def daemon_exec(self):
        try:
            self.sock = u_socket(self.manAddr, self.sockAddr)
            self.sock.connect()
        except Exception, msg:
            fd = open(self.logPath, 'a')
            fd.write("[%s]\t%s\n"%(self.currentTime(),msg))
            fd.close()

        #connect database
        self.db = ss_database(self.dbPath)
        self.db.connect()
        ''' 
        #add ss-server from database
        sql = "select id,password from port"
        total = 0
        success = 0
        for port_info in self.db.db.execute(sql):
            total += 1
            ack = self.sock.cmd(createCMD("add", server_port = int(port_info[0]), password = port_info[1]))
            if ack == "ok":
                success += 1
        logfd = open(self.logPath,'a')
        self.deamon_log(logfd,"open server port from data base, total: %d success: %d"%(total,success))
        logfd.close()
        '''
        #init port pool, will use database soon
        sql = "select id from port"
        result = self.db.db.execute(sql)
        for info in result:
            self.portpool.set(int(info[0]),1)

        #create thread
        thd_control = threading.Thread(target = self.daemon_control)
        thd_update = threading.Thread(target = self.daemon_generalupdate)
        
        #thread start
        thd_control.start()
        thd_update.start()

        try:
            while self.daemon_isRun:
                try:
                    cmd = self.cmd_queue.get(timeout=11)
                except Queue.Empty:
                    break
                self.daemon_process(cmd)
        except Exception,msg:
            test = open('/tmp/test.log','w')
            test.write("[%s]%s"%(self.currentTime(),msg))
            test.close()

        self.db.disconnect()
        
        logfd = open(self.logPath,'a')
        logfd.write("[%s]\tdaemon end\n"%self.currentTime())
        logfd.close()

    def daemon_create(self):
        pid = os.fork()
        if pid > 0:
            fd = open(self.pidPath, 'w')
            if fd:
                fd.write("%s"%pid)
                fd.flush()
                fd.close()
            sys.exit(1)
        else:
            logfd = open(self.logPath, 'w')
            if not logfd:
                sys.exit(1)
        logfd.write("[%s]\tstart daemon.\n"%self.currentTime())

        os.umask(0)
        if os.setsid():
            logfd.close()
            sys.exit(1)
        logfd.write("[%s]\tset sid.\n"%self.currentTime())
        logfd.close()

        os.chdir("/")
        os.close(0)
        os.close(1)
        os.close(2)

    def currentTime(self):
        return time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time()))

    def daemon_generalupdate(self):
        while self.daemon_isRun:
            self.cmd_queue.put('update')
            time.sleep(10)
    
    def daemon_process(self, cmd):
        if cmd == 'update':
            recvMsg = self.sock.cmd(createCMD("ping"))
            recvMsg = json.loads(recvMsg[6:])
            for server in recvMsg:
                mb = (recvMsg[server]/1024.0)/1024.0
                #first update
                sql = "update port set datausage=%.2f,updatetime=current_timestamp where id=%d"%(mb, int(server))
                self.db.db.execute(sql)
                '''
                #if no update happened then insert one
                sql = "insert into port (id, datausage, updatetime) select %d,%.2f,current_timestamp where( select Changes() = 0)"%(int(server), mb)
                self.db.db.execute(sql)
                '''
            self.db.db.commit()
        elif cmd == 'save+':
            sql = "select id,datausage,datahistory from port"
            result = self.db.db.execute(sql)
            for info in result:
                port = int(info[0])
                history = float(info[1])+float(info[2])
                sql = "update port set datahistory=%.2f where id=%d"%(history, port)
                self.db.db.execute(sql)
            self.db.db.commit()
        elif cmd == 'save':
            sql = "select id,datausage,datahistory from port"
            result = self.db.db.execute(sql)
            for info in result:
                port = int(info[0])
                history = float(info[1])
                sql = "update port set datahistory=%.2f where id=%d"%(history, port)
                self.db.db.execute(sql)
            self.db.db.commit()
        elif cmd == 'reset':
            sql = "update port set datahistory=0.0"
            self.db.db.execute(sql)
            self.db.db.commit()
        elif 'add' in cmd:
            args = cmd.split(",")
            info_list = [args[3],args[4]]
            addr = (args[1],int(args[2]))
            ack = self.sock.cmd(createCMD("add", server_port = int(info_list[0]), password = info_list[1]))
            if ack == "ok":
                sql = "insert into port (id, password) values (?,?)"
                para = (int(info_list[0]),info_list[1])
                self.db.db.execute(sql,para)
                self.db.db.commit()
                self.portpool.set(int(info_list[0]),1)
            remotesock = socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
            remotesock.sendto("%s"%ack,addr)
            remotesock.close()
        elif 'remove' in cmd:
            args = cmd.split(",")
            info_list = [args[3]]
            addr = (args[1],int(args[2]))
            ack = self.sock.cmd(createCMD("remove", server_port = int(info_list[0])))
            if ack == "ok":
                sql = "delete from port where id=?"
                para = (int(info_list[0]),)
                self.db.db.execute(sql,para)
                self.db.db.commit()
                self.portpool.set(int(info_list[0]),0)
            remotesock = socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
            remotesock.sendto("%s"%ack,addr)
            remotesock.close()

    def parseCMD(self, cmd):
        start = cmd.find('{')
        end = cmd.find('}')
        if start==-1 or end==-1:
            return []
        msg = cmd[start+1:end].split(",")
        return msg
    
    def deamon_log(self, fd, msg):
        fd.write("[%s]\t%s\n"%(self.currentTime(), msg))

    def daemon_control(self):
        try:
            server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            addr = ('127.0.0.1',7000)
            server.bind(addr)
        except Exception, msg:
            logfd = open(self.logPath, 'a')
            logfd.write("[%s]\t%s\n"%(self.currentTime(), msg))
            logfd.close()
            self.daemon_isRun = False
            return

        while True:
            data, addr = server.recvfrom(128)
            logfd = open(self.logPath, 'a')
            if 'stop' in data:
                log = "daemon will be closed in 10 seconds."
                logfd.write("[%s]\t%s\n"%(self.currentTime(),log))
                server.sendto(log,addr)
                logfd.close()
                break
            elif 'list' in data:
                logfd.write("[%s]\trecv cmd list\n"%self.currentTime())
                tmpdb = ss_database(self.dbPath)
                tmpdb.connect()
                sql = "select * from port"
                for port in tmpdb.db.execute(sql):
                    server.sendto("%s\n"%port.__str__(),addr)
                tmpdb.disconnect()
            elif 'save_add' in data:
                logfd.write("[%s]\trecv cmd save and add\n"%self.currentTime())
                self.cmd_queue.put('save+')
            elif 'save_cover' in data:
                logfd.write("[%s]\trecv cmd save and cover\n"%self.currentTime())
                self.cmd_queue.put('save')
            elif 'reset' in data:
                logfd.write("[%s]\trecv cmd reset\n"%self.currentTime())
                self.cmd_queue.put('reset')
            elif 'get' in data:
                cmd = self.parseCMD(data)
                if len(cmd)==0:
                    msg = "%d"%0
                else:
                    msg = cmd[0]
                logfd.write("[%s]\trecv cmd get\n"%self.currentTime())
                tmpdb = ss_database(self.dbPath)
                tmpdb.connect()
                sql = "select * from port where id=%d"%int(msg)
                result = ""
                for data in tmpdb.db.execute(sql):
                    result = data.__str__()
                tmpdb.disconnect()
                if result=="":
                    server.sendto("None",addr)
                else:
                    server.sendto(result,addr)
            elif 'port_available' in data:
                port = self.portpool.get()
                if port==-1:
                    server.sendto("None",addr)
                else:
                    server.sendto("%d"%port,addr)
            elif 'add' in data:
                self.deamon_log(logfd,"recv cmd add")
                cmd = self.parseCMD(data)
                try:
                    if len(cmd)<2:
                        raise ssmanErr("invalid args")
                    try:
                        port = int(cmd[0])
                    except ValueError:
                        raise ssmanErr("invalid args")
                    ret = self.portpool.check(port)
                    if ret==-1 or ret>0:
                        raise ssmanErr("invalid port or port already exists")
                    self.cmd_queue.put('add,%s,%d,%s,%s'%(addr[0],addr[1],cmd[0],cmd[1]))
                except ssmanErr, err:
                    self.deamon_log(logfd,"cmd add failed: %s"%err.msg)
                    server.sendto("ERR",addr)
            elif 'remove' in data:
                self.deamon_log(logfd,"recv cmd remove")
                cmd = self.parseCMD(data)
                try:
                    if len(cmd)<1:
                        raise ssmanErr("invalid args")
                    try:
                        port = int(cmd[0])
                    except ValueError:
                        raise ssmanErr("invalid args")
                    ret = self.portpool.check(port)
                    if ret<1:
                        raise ssmanErr("invalid port or port not exists")
                    self.cmd_queue.put('remove,%s,%d,%s'%(addr[0],addr[1],cmd[0]))
                except ssmanErr, err:
                    self.deamon_log(logfd,"cmd remove failed: %s"%err.msg)
                    server.sendto("ERR",addr)
            logfd.close()
        server.close()
        self.daemon_isRun = False

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
    cmd_dbstatus= False

    password    = None
    managerAddr  = "/tmp/manager.sock"
    socketAddr  = "/tmp/client.sock"
    pidPath     = ""

    try:
        try:
            opts, args = getopt.getopt(argv[1:], "a:df:hlmr:", ["password=", "add-json=", "manager-address=", "socket-address=", "help"])
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
            elif opt in ('-d'):
                cmd_dbstatus = True

        if cmd_add and (not password):
            raise Usage("opt '-a' need '--password'")
        if cmd_monitor and cmd_service:
            raise Usage("can not use opt '-m' and '-f' at the same time")

    except Usage, err:
        print >>sys.stderr, ERR, err.msg
        print >>sys.stderr, err.__doc__
        return 1
    try:
        if ( cmd_add or cmd_ping or cmd_remove or cmd_addjson or cmd_monitor ):
            try:
                sock = u_socket(managerAddr, socketAddr)
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

            try:
                if cmd_monitor == True:
                    portMonitor(sock)
            except Exception, msg:
                print >>sys.stderr, WARN, msg, "opt '-m' failed."

        elif cmd_dbstatus:
            db = ss_database("/home/tupers/test.db")
            db.connect()
            for info in db.list():
                print info
            db.disconnect()

        elif cmd_service:
            daemon = ss_daemon(pidPath=pidPath)
            daemon.daemon_create()
            daemon.daemon_exec()
            '''
            ****** Operation End ******
            '''

    except Usage, err:
        print >>sys.stderr, ERR, err.msg
        return 2

if __name__ == '__main__':
    sys.exit(main())
