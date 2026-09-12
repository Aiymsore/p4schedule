"""P4 Schedule 课表导入服务。

启动（在 server/ 目录下）：
    uvicorn main:app --host 0.0.0.0 --port 8000

环境变量：
    ALLOWED_ORIGINS   逗号分隔的跨域来源（前端留在 GitHub Pages 时必填）
    UPLOAD_TOKEN      设置后 /api/parse 要求请求头 X-Upload-Token 匹配
    COURSES_PATH      courses.json 路径，默认仓库根的 courses.json
    SEMESTER_START    学期第一周的周一，默认 2026-09-07
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from parsing import ParseError, parse_file

REPO_ROOT = Path(__file__).resolve().parent.parent
COURSES_PATH = Path(os.environ.get("COURSES_PATH", REPO_ROOT / "courses.json"))
UPLOAD_TOKEN = os.environ.get("UPLOAD_TOKEN", "")

app = FastAPI(title="P4 Schedule Import API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip()
        for origin in os.environ.get("ALLOWED_ORIGINS", "").split(",")
        if origin.strip()
    ],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

_write_lock = threading.Lock()


def write_courses(entries: list[dict]) -> None:
    """先备份再原子覆盖，避免写一半损坏数据。"""
    with _write_lock:
        if COURSES_PATH.exists():
            backup = COURSES_PATH.with_suffix(".json.bak")
            backup.write_bytes(COURSES_PATH.read_bytes())

        temp_path = COURSES_PATH.with_suffix(".json.tmp")
        temp_path.write_text(
            json.dumps(entries, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temp_path, COURSES_PATH)


@app.post("/api/parse")
async def parse_upload(request: Request, file: UploadFile = File(...)):
    if UPLOAD_TOKEN and request.headers.get("X-Upload-Token") != UPLOAD_TOKEN:
        raise HTTPException(status_code=401, detail="上传令牌不正确。")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="上传的文件是空的。")
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="文件超过 10MB 限制。")

    try:
        entries = parse_file(file.filename or "", data)
    except ParseError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    write_courses(entries)
    return {"count": len(entries), "courses": entries}


@app.get("/api/courses")
async def get_courses():
    if not COURSES_PATH.exists():
        raise HTTPException(status_code=404, detail="courses.json 不存在。")
    return JSONResponse(content=json.loads(COURSES_PATH.read_text(encoding="utf-8")))


# 前端静态文件（同源模式：浏览器直接访问 VPS 即可，无需配置 API 地址）
app.mount("/", StaticFiles(directory=REPO_ROOT, html=True), name="static")
