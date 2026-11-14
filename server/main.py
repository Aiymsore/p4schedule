"""本地启动：python -m uvicorn main:app --host 127.0.0.1 --port 8000"""
import logging
import os
import secrets
from pathlib import Path
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from database import import_courses, read_courses
from parsing import ParseError, parse_file

REPO_ROOT = Path(__file__).resolve().parent.parent
app = FastAPI(title="P4 Schedule MySQL Import API")
ALLOWED_ORIGINS = [s.strip().rstrip("/") for s in os.environ.get("ALLOWED_ORIGINS", "").split(",") if s.strip()]
app.add_middleware(
    CORSMiddleware, allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST"], allow_headers=["X-Upload-Token", "Content-Type"],
)
logger = logging.getLogger(__name__)


@app.get("/api/courses")
def get_courses():
    try:
        return read_courses()
    except Exception:
        logger.exception("读取数据库失败")
        raise HTTPException(503, "数据库读取失败，请检查终端日志及数据库配置")


@app.post("/api/parse")
def parse_upload(request: Request, file: UploadFile = File(...)):
    origin = request.headers.get("origin")
    if (origin and origin.rstrip("/") != str(request.base_url).rstrip("/")
            and origin.rstrip("/") not in ALLOWED_ORIGINS):
        raise HTTPException(403, "此网页来源未获允许")
    token = os.environ.get("UPLOAD_TOKEN", "")
    if ALLOWED_ORIGINS and not token:
        raise HTTPException(503, "云端上传尚未配置导入口令")
    if token and not secrets.compare_digest(
        request.headers.get("X-Upload-Token", "").encode("utf-8"), token.encode("utf-8")
    ):
        raise HTTPException(401, "导入口令不正确，请重新输入")
    data = file.file.read(10 * 1024 * 1024 + 1)
    if not data:
        raise HTTPException(400, "上传文件为空")
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(413, "文件超过10MB")
    try:
        entries = parse_file(file.filename or "", data)
        result = import_courses(entries)
    except (ParseError, ValueError) as error:
        raise HTTPException(400, str(error)) from error
    except Exception:
        logger.exception("课表导入失败")
        raise HTTPException(503, "导入失败，请检查终端日志；未提交的写入已回滚")
    try:
        courses = read_courses()
    except Exception:
        logger.exception("导入已提交，但刷新读取失败")
        raise HTTPException(503, "导入已保存，但刷新失败，请稍后刷新页面；重复上传会跳过相同安排")
    return {**result, "count": len(courses), "courses": courses}


@app.get("/")
def index():
    return FileResponse(REPO_ROOT / "index.html")


@app.get("/app.js")
def javascript():
    return FileResponse(REPO_ROOT / "app.js", media_type="application/javascript")


@app.get("/style.css")
def stylesheet():
    return FileResponse(REPO_ROOT / "style.css", media_type="text/css")


app.mount("/assets", StaticFiles(directory=REPO_ROOT / "assets"), name="assets")
