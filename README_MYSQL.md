> 当前分支已升级为账户隔离版，部署和迁移请先阅读 README_ACCOUNTS.md。以下内容为历史单人版说明。

# 本地 MySQL 课表导入

网页的“导入课表”上传 xls/xlsx/docx，FastAPI 解析后写入 `p4schedule`，页面重载也从 MySQL 读取。本地服务不再读取 courses.json；GitHub Pages 在尚未配置 API_BASE 时继续读取静态 courses.json，上传会提示云端导入尚未启用。

本次仅供本机学习、单人单学期使用，保留旧记录。相同课程名、教师、日期、节次、教室的安排跳过；修改过的安排会追加，不会自动删除旧安排。练习数据仍保留。不同学期请先完善学期及用户模型。

## 启动（PowerShell）

停止原来占用8000端口的 schedule_api 服务（在其终端按 Ctrl+C）。

```powershell
Set-Location 'D:\0creation\course_timetable\p4schedule\server'
$dbSecret = Read-Host '请输入 schedule_app 的密码' -MaskInput
$env:SCHEDULE_DB_PASSWORD = $dbSecret
Remove-Variable dbSecret
& 'D:\0creation\course_timetable\import\.venv\Scripts\python.exe' -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

只从 http://127.0.0.1:8000/ 打开页面，避免 GitHub Pages 或 Live Server。浏览器第一次请强制刷新一次（Ctrl+F5）。点击导入，选择 download.xls；页面显示解析、新增、跳过数量。刷新页面验证数据仍然存在。

已有完整170条课表时，再上传相同文件，预期解析170、新增0、跳过170。数据库里的两条练习安排仍显示，因此总数可能172。不要用总数判断新增条数。

密码仅保存在本次终端环境变量中；代码不含密码。查询接口不需要上传令牌。本机版本没有用户登录，不应直接发布到公网。

## 实现

- server/main.py：网页文件、GET /api/courses、POST /api/parse。
- server/parsing.py：文件解析，支持四节实验课的05060708编码。
- server/database.py：校验、参数化SQL、统一事务提交/回滚、数据库连接级导入锁。
- app.js：请求MySQL查询接口，显示导入统计。

所有导入输入先验证再写入。数据库中途报错回滚本次事务；提交后刷新失败会明确提示已保存。导入锁覆盖本Web接口；不要同时运行旧命令行导入脚本。当前复用课程名称字段保留[课程类型]后缀以匹配先前导入数据，后续可以迁移为独立类型字段。

## 检查

```powershell
& 'D:\0creation\course_timetable\import\.venv\Scripts\python.exe' -m pytest -q
```

在server目录运行。数据库事务与接口测试使用模拟连接，不会改动真实数据库；真实上传需使用你本机的数据库密码自行验证。
