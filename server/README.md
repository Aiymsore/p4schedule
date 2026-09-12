# P4 Schedule 导入服务（FastAPI）

网页上传 xlsx / xls / docx 课表文件 → 自适应解析 → 原子覆盖 `courses.json` → 所有访问者看到新课表。
PNG 等其他格式暂不支持，接口会返回 400 提示。

## 本地运行

```bash
cd server
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```

浏览器打开 `http://<服务器IP>:8000` 即是完整网站（FastAPI 同时托管前端静态文件），
页面的「导入课表」按钮上传文件即可。

## 环境变量

| 变量 | 作用 | 默认 |
|---|---|---|
| `ALLOWED_ORIGINS` | 允许跨域调用 API 的来源，逗号分隔。**前端留在 GitHub Pages 时必填**，例如 `https://aiymsore.github.io` | 空（不允许跨域） |
| `UPLOAD_TOKEN` | 设置后 `/api/parse` 要求请求头 `X-Upload-Token` 匹配，防止任何人覆盖课表 | 空（不鉴权，**有风险**） |
| `COURSES_PATH` | courses.json 的路径 | 仓库根 `courses.json` |
| `SEMESTER_START` | 学期第一周的周一（ISO 日期），用于从周数推算日期 | `2026-09-07` |

## VPS 部署（systemd 开机自启）

```ini
# /etc/systemd/system/p4schedule.service
[Unit]
Description=P4 Schedule import service
After=network.target

[Service]
WorkingDirectory=/opt/p4schedule/server
Environment=UPLOAD_TOKEN=换成随机长字符串
Environment=ALLOWED_ORIGINS=https://aiymsore.github.io
ExecStart=/usr/bin/python3 -m uvicorn main:app --host 127.0.0.1 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now p4schedule
```

建议 nginx 反向代理并配 HTTPS：

```nginx
server {
    server_name your-domain.com;
    location / {
        proxy_pass http://127.0.0.1:8000;
        client_max_body_size 12m;
    }
    # certificates via certbot --nginx
}
```

## 前端如何连接

- **同源模式（推荐）**：直接访问 VPS 上的站点，`app.js` 里 `API_BASE = ""` 保持不变。
- **GitHub Pages 模式**：把 `app.js` 顶部的 `API_BASE` 改成 `https://your-domain.com`，
  并在 VPS 上设置 `ALLOWED_ORIGINS=https://aiymsore.github.io`。

## 解析器适配新格式

表头按关键词定位（`server/parsing.py` 的 `COLUMN_ALIASES`）。遇到识别失败的新导出格式，
在对应字段的别名列表里加一个关键词即可，例如课程列叫「科目」就往 `course` 里加 `"科目"`。

覆盖 `courses.json` 前会自动备份到 `courses.json.bak`。
