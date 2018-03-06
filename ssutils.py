import sqlite3

class ss_database:
    def __init__(self, dbPath):
        self.dbPath = dbPath
        self.connect()
        sql = "create table IF NOT EXISTS port(id int primary key, datausage real default 0.0, datahistory real default 0.0, updatetime updatetime default current_timestamp, password text)"
        self.cursor.execute(sql)
        self.disconnect()

    def connect(self):
        self.db = sqlite3.connect(self.dbPath)
        self.cursor = self.db.cursor()

    def disconnect(self):
        self.cursor.close()
        self.db.close()

    def list(self, port=0):
        if port:
            sql = "select * from port where id=%d"%int(port)
        else:
            sql = "select * from port"
        ports = self.cursor.execute(sql)
        return ports.fetchall()

class ssmanErr(Exception):
    def __init__(self, msg):
        self.msg = msg
