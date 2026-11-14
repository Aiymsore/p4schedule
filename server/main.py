"""账户隔离版 API；先运行 migrate_accounts.py，再启动服务。"""
import logging
import os
from datetime import date
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
import pymysql

import auth
import database
from parsing import ParseError, parse_file

REPO_ROOT=Path(__file__).resolve().parent.parent
app=FastAPI(title="P4 Schedule Account API")
ALLOWED_ORIGINS=[s.strip().rstrip("/") for s in os.environ.get("ALLOWED_ORIGINS","").split(",") if s.strip()]
app.add_middleware(CORSMiddleware,allow_origins=ALLOWED_ORIGINS,
                   allow_methods=["GET","POST","DELETE"],
                   allow_headers=["Authorization","Content-Type"])
logger=logging.getLogger(__name__)
bearer=HTTPBearer(auto_error=False)


@app.exception_handler(RequestValidationError)
async def invalid_input(request,error):
    # 不将请求中的密码或完整输入回显到错误响应。
    return JSONResponse(status_code=422,content={"detail":"输入格式不正确，请检查用户名、密码长度、课表编号和日期"})


@app.middleware("http")
async def private_api_responses(request,call_next):
    response=await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"]="no-store"
        response.headers["Pragma"]="no-cache"
    response.headers["X-Content-Type-Options"]="nosniff"
    return response


@app.exception_handler(pymysql.MySQLError)
async def database_error(request,error):
    logger.error("数据库操作失败",exc_info=(type(error),error,error.__traceback__))
    return JSONResponse(status_code=503,content={"detail":"数据库暂时不可用，请稍后重试"})


@app.exception_handler(database.ScheduleNotFound)
async def schedule_not_found(request,error):
    return JSONResponse(status_code=404,content={"detail":"课表不存在或无权访问"})


@app.exception_handler(auth.RateLimited)
async def too_many_requests(request,error):
    return JSONResponse(status_code=429,content={"detail":"操作过于频繁，请稍后再试"},headers={"Retry-After":"900"})


class Credentials(BaseModel):
    model_config=ConfigDict(extra="forbid")
    username: str=Field(min_length=3,max_length=32)
    password: SecretStr=Field(min_length=12,max_length=128)


class ScheduleInput(BaseModel):
    model_config=ConfigDict(extra="forbid")
    label: str=Field(min_length=1,max_length=80)
    semester_start: date

    @field_validator("label")
    @classmethod
    def label_not_blank(cls,value):
        if not value.strip():
            raise ValueError("课表名称不能为空")
        return value.strip()

    @field_validator("semester_start")
    @classmethod
    def monday_start(cls,value):
        if value.weekday()!=0:
            raise ValueError("学期第一周起点请选择周一")
        if not 2000<=value.year<=2100:
            raise ValueError("学期年份超出范围")
        return value


def user_from_credentials(credentials: HTTPAuthorizationCredentials | None=Depends(bearer)):
    if credentials is None or credentials.scheme.lower()!="bearer":
        raise HTTPException(401,"请先登录",headers={"WWW-Authenticate":"Bearer"})
    try:
        return auth.authenticate(credentials.credentials)
    except auth.InvalidLogin:
        raise HTTPException(401,"登录已过期，请重新登录",headers={"WWW-Authenticate":"Bearer"})


def limit(request,action,username=None):
    peer=request.client.host if request.client else "unknown"
    auth.consume_rate_limit(action+":ip",peer,50 if action=="login" else 10,900 if action=="login" else 3600)
    if username is not None:
        auth.consume_rate_limit(action+":user",username.strip().lower(),15,900)


@app.post("/api/auth/register",status_code=201)
def register(body: Credentials,request: Request):
    limit(request,"register")
    try:
        return auth.register(body.username,body.password.get_secret_value())
    except auth.UsernameTaken:
        raise HTTPException(409,"用户名已被使用")
    except ValueError as error:
        raise HTTPException(400,str(error))


@app.post("/api/auth/login")
def login(body: Credentials,request: Request):
    limit(request,"login",body.username)
    try:
        return auth.login(body.username,body.password.get_secret_value())
    except (auth.InvalidLogin,ValueError):
        raise HTTPException(401,"用户名或密码不正确")


@app.get("/api/auth/me")
def me(user=Depends(user_from_credentials)):
    return user


@app.post("/api/auth/logout")
def logout(credentials: HTTPAuthorizationCredentials=Depends(bearer),user=Depends(user_from_credentials)):
    auth.logout(credentials.credentials)
    return {"message":"已退出登录"}


@app.get("/api/schedules")
def schedules(user=Depends(user_from_credentials)):
    return database.list_schedules(user["id"])


@app.post("/api/schedules",status_code=201)
def add_schedule(body: ScheduleInput,user=Depends(user_from_credentials)):
    try:
        return database.create_schedule(user["id"],body.label,body.semester_start)
    except ValueError as error:
        raise HTTPException(400,str(error))


@app.get("/api/courses")
def courses(schedule_id: int | None=Query(None,gt=0),user=Depends(user_from_credentials)):
    return database.read_courses(user["id"],schedule_id)


@app.delete("/api/schedules/{schedule_id}/courses")
def clear_courses(schedule_id: int,user=Depends(user_from_credentials)):
    return database.clear_schedule(user["id"],schedule_id)


@app.post("/api/parse")
async def upload(file: UploadFile=File(...),schedule_id: int=Query(...,gt=0),
                 user=Depends(user_from_credentials)):
    # 读取文件之前核对归属。用户传来的课表编号本身不代表访问权限。
    def find_schedule():
        connection=database.connect()
        try:
            with connection.cursor() as cursor:
                return database.owned_schedule(cursor,user["id"],schedule_id)
        finally:
            connection.close()
    schedule=await run_in_threadpool(find_schedule)
    data=await file.read(10*1024*1024+1)
    if not data:
        raise HTTPException(400,"上传文件为空")
    if len(data)>10*1024*1024:
        raise HTTPException(413,"文件超过10MB")
    try:
        entries=await run_in_threadpool(parse_file,file.filename or "",data,schedule["semester_start"])
        result=await run_in_threadpool(database.import_courses,entries,user["id"],schedule_id)
    except (ParseError,ValueError) as error:
        raise HTTPException(400,str(error))
    try:
        saved=await run_in_threadpool(database.read_courses,user["id"],schedule_id)
    except pymysql.MySQLError:
        logger.exception("已导入但刷新读取失败")
        raise HTTPException(503,"导入已保存，刷新失败；请重新加载，重复上传会跳过相同安排")
    return {**result,"count":len(saved),"courses":saved}


@app.get("/api/health")
def health():
    return {"status":"ok","accounts":True}


@app.get("/")
def index():
    return FileResponse(REPO_ROOT/"index.html")


@app.get("/app.js")
def javascript():
    return FileResponse(REPO_ROOT/"app.js",media_type="application/javascript")


@app.get("/style.css")
def stylesheet():
    return FileResponse(REPO_ROOT/"style.css",media_type="text/css")


app.mount("/assets",StaticFiles(directory=REPO_ROOT/"assets"),name="assets")
