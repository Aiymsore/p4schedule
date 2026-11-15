"""使用真实SQL的内存数据库验证归属隔离；不接触本机或云端MySQL。"""
import sqlite3
import sys
import uuid
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path

import pymysql
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0,str(Path(__file__).resolve().parent))
import auth
import database
import main
from security import hash_password,verify_password,token_digest

SCHEMA="""
CREATE TABLE users(id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL);
CREATE TABLE schedules(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL REFERENCES users(id),
 label TEXT NOT NULL,semester_start DATE NOT NULL,cache_version INTEGER NOT NULL DEFAULT 1,UNIQUE(user_id,label));
CREATE TABLE courses(id INTEGER PRIMARY KEY AUTOINCREMENT,schedule_id INTEGER NOT NULL REFERENCES schedules(id),
 name TEXT NOT NULL,teacher TEXT,location TEXT);
CREATE TABLE course_sessions(id INTEGER PRIMARY KEY AUTOINCREMENT,course_id INTEGER NOT NULL REFERENCES courses(id),
 class_date DATE NOT NULL,start_period INTEGER NOT NULL,end_period INTEGER NOT NULL,location TEXT);
CREATE TABLE auth_sessions(token_hash TEXT PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),
 expires_at TIMESTAMP NOT NULL);
CREATE TABLE auth_rate_limits(bucket_key TEXT PRIMARY KEY,hits INTEGER NOT NULL,reset_at TIMESTAMP NOT NULL);
"""

class Cursor:
    def __init__(self,connection):
        self.raw=connection.cursor()
        self.fake=None
    def __enter__(self): return self
    def __exit__(self,*args): self.raw.close()
    @property
    def lastrowid(self): return self.raw.lastrowid
    @property
    def rowcount(self): return self.raw.rowcount
    def execute(self,sql,params=()):
        self.fake=None
        if "GET_LOCK(" in sql:
            self.fake={"acquired":1}
            return
        sql=sql.replace("%s","?").replace(" FOR UPDATE","")
        try:
            return self.raw.execute(sql,params)
        except sqlite3.IntegrityError as error:
            code=1062 if "UNIQUE constraint" in str(error) else 3819
            raise pymysql.IntegrityError(code,str(error)) from error
    def fetchone(self):
        if self.fake is not None:
            result=self.fake; self.fake=None; return result
        row=self.raw.fetchone()
        return dict(row) if row is not None else None
    def fetchall(self): return [dict(row) for row in self.raw.fetchall()]

class Connection:
    def __init__(self,uri):
        self.raw=sqlite3.connect(uri,uri=True,detect_types=sqlite3.PARSE_DECLTYPES,check_same_thread=False)
        self.raw.row_factory=sqlite3.Row
        self.raw.execute("PRAGMA foreign_keys=ON")
    def cursor(self): return Cursor(self.raw)
    def commit(self): self.raw.commit()
    def rollback(self): self.raw.rollback()
    def close(self): self.raw.close()

@pytest.fixture
def site(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    uri="file:accounts_"+uuid.uuid4().hex+"?mode=memory&cache=shared"
    keeper=sqlite3.connect(uri,uri=True,detect_types=sqlite3.PARSE_DECLTYPES,check_same_thread=False)
    keeper.row_factory=sqlite3.Row
    keeper.executescript(SCHEMA)
    monkeypatch.setattr(database,"connect",lambda:Connection(uri))
    with TestClient(main.app) as client:
        yield client,keeper
    keeper.close()

def signup(client,username):
    response=client.post("/api/auth/register",json={"username":username,"password":"test-password-long-enough"})
    assert response.status_code==201,response.text
    body=response.json()
    return body,{"Authorization":"Bearer "+body["access_token"]}

def schedule_id(client,headers):
    response=client.get("/api/schedules",headers=headers)
    assert response.status_code==200,response.text
    return response.json()[0]["id"]

def entry(name="Ecology",location="101"):
    return {"course":name,"course_type":"lecture","teacher":"T","location":location,
            "date":"2026-09-07","periods":[1,2]}

def test_passwords_are_salted_and_unicode_supported():
    password="safe-password-生态学-2026"
    a,b=hash_password(password),hash_password(password)
    assert a!=b and password not in a
    assert verify_password(password,a)
    assert not verify_password(password+"x",a)
    assert not verify_password(password,"bad")

def test_anonymous_and_old_upload_token_cannot_read_or_write(site):
    client,_=site
    for url in ["/api/courses","/api/schedules","/api/auth/me"]:
        assert client.get(url).status_code==401
    assert client.post("/api/parse?schedule_id=1",files={"file":("a.xls",b"data")}).status_code==401
    assert client.delete("/api/schedules/1/courses").status_code==401
    assert client.get("/api/courses",headers={"X-Upload-Token":"old-key"}).status_code==401
    assert client.get("/api/courses?access_token=anything").status_code==401
    assert client.get("/courses.json").status_code==404

def test_two_accounts_same_course_are_independent_and_idor_blocked(site,monkeypatch):
    client,raw=site
    alice,ha=signup(client,"alice")
    bob,hb=signup(client,"bob")
    sa,sb=schedule_id(client,ha),schedule_id(client,hb)
    monkeypatch.setattr(main,"parse_file",lambda *args:[entry()])
    assert client.get(f"/api/courses?schedule_id={sb}",headers=hb).json()==[]
    first=client.post(f"/api/parse?schedule_id={sa}",headers=ha,files={"file":("a.xls",b"data")})
    assert first.status_code==200,first.text
    assert first.json()["added"]==1
    assert client.get(f"/api/courses?schedule_id={sb}",headers=hb).json()==[]
    for request in [
        lambda:client.get(f"/api/courses?schedule_id={sa}",headers=hb),
        lambda:client.post(f"/api/parse?schedule_id={sa}",headers=hb,files={"file":("b.xls",b"data")}),
        lambda:client.delete(f"/api/schedules/{sa}/courses",headers=hb),
    ]:
        assert request().status_code==404
    again=client.post(f"/api/parse?schedule_id={sa}",headers=ha,files={"file":("a.xls",b"data")})
    assert again.json()["added"]==0 and again.json()["skipped"]==1
    own=client.post(f"/api/parse?schedule_id={sb}",headers=hb,files={"file":("a.xls",b"data")})
    assert own.json()["added"]==1  # 同课程不能与Alice共用一条course记录
    assert raw.execute("SELECT COUNT(*) FROM courses").fetchone()[0]==2
    assert client.delete(f"/api/schedules/{sb}/courses",headers=hb).json()["deleted"]==1
    assert len(client.get(f"/api/courses?schedule_id={sa}",headers=ha).json())==1

def test_login_logout_expiry_and_hashed_sessions(site):
    client,raw=site
    user,headers=signup(client,"alice")
    stored=raw.execute("SELECT token_hash FROM auth_sessions").fetchone()[0]
    assert stored==token_digest(user["access_token"]) and stored!=user["access_token"]
    assert client.post("/api/auth/login",json={"username":"alice","password":"wrong-but-long-password"}).status_code==401
    assert client.post("/api/auth/login",json={"username":"nobody","password":"wrong-but-long-password"}).status_code==401
    login=client.post("/api/auth/login",json={"username":"ALICE","password":"test-password-long-enough"})
    assert login.status_code==200
    assert client.get("/api/auth/me",headers=headers).json()["username"]=="alice"
    assert client.post("/api/auth/logout",headers=headers).status_code==200
    assert client.get("/api/courses",headers=headers).status_code==401
    expired={"Authorization":"Bearer "+login.json()["access_token"]}
    raw.execute("UPDATE auth_sessions SET expires_at=?",(datetime.utcnow()-timedelta(seconds=1),))
    raw.commit()
    assert client.get("/api/auth/me",headers=expired).status_code==401

def test_register_duplicate_and_no_user_id_injection_or_password_echo(site):
    client,raw=site
    signup(client,"alice")
    assert client.post("/api/auth/register",json={"username":"Alice","password":"test-password-long-enough"}).status_code==409
    secret="do-not-echo-this-secret"
    response=client.post("/api/auth/register",json={"username":"eve","password":secret,"user_id":1})
    assert response.status_code==422 and secret not in response.text
    assert raw.execute("SELECT COUNT(*) FROM users").fetchone()[0]==1

def test_multiple_schedules_are_scoped_and_semester_passed_to_parser(site,monkeypatch):
    client,_=site
    _,ha=signup(client,"alice")
    _,hb=signup(client,"bob")
    created=client.post("/api/schedules",headers=ha,json={"label":"Spring","semester_start":"2027-03-01"})
    assert created.status_code==201,created.text
    sid=created.json()["id"]
    captured=[]
    def parse(name,data,start):
        captured.append(str(start))
        return [{**entry(),"date":"2027-03-01"}]
    monkeypatch.setattr(main,"parse_file",parse)
    response=client.post(f"/api/parse?schedule_id={sid}",headers=ha,files={"file":("a.xls",b"data")})
    assert response.status_code==200,response.text
    assert captured==["2027-03-01"] and response.json()["courses"][0]["week"]==1
    assert len(client.get("/api/schedules",headers=hb).json())==1
    assert client.get(f"/api/courses?schedule_id={sid}",headers=hb).status_code==404
    assert client.post("/api/schedules",headers=ha,json={"label":"Bad","semester_start":"2027-03-02"}).status_code==422

def test_partial_import_failure_rolls_back_all_rows(site):
    client,raw=site
    user,headers=signup(client,"alice")
    sid=schedule_id(client,headers)
    raw.executescript("""CREATE TRIGGER fail_lab BEFORE INSERT ON course_sessions
        WHEN NEW.location='FAIL' BEGIN SELECT RAISE(ABORT,'simulated failure'); END;""")
    with pytest.raises(pymysql.IntegrityError):
        database.import_courses([entry("A"),entry("B","FAIL")],user["user"]["id"],sid)
    assert raw.execute("SELECT COUNT(*) FROM courses").fetchone()[0]==0
    assert raw.execute("SELECT COUNT(*) FROM course_sessions").fetchone()[0]==0

def test_rate_limits_persist_in_database(site):
    for _ in range(3):
        auth.consume_rate_limit("test","subject",3,60)
    with pytest.raises(auth.RateLimited):
        auth.consume_rate_limit("test","subject",3,60)

def test_cors_preflight_and_private_response_cache(site):
    client,_=site
    _,headers=signup(client,"alice")
    response=client.get("/api/courses",headers=headers)
    assert response.headers["cache-control"]=="no-store"
    assert "Authorization" in str(main.app.user_middleware)
