# 账户和个人课表

每个账户只能读取、导入和清空自己的课表，可以建立最多12份课表。新账户从空课表开始；旧共享课表由管理员迁移到明确指定的账户，不会分配给首个注册者。已存在的Git历史中的旧公开课表不会因此变成私密数据。

本版本没有邮箱验证、自助找回密码和管理员网页。请保管自己的账户密码；它与MySQL密码、SSH密码不同。问卷评分仍保存在当前浏览器，按用户编号和课表编号隔离，不跨设备同步。课表本身存储在MySQL。

## 升级顺序

先升级后端并迁移，再发布GitHub Pages前端。当前分支只用于准备和服务器验证，不自动替换main上的Pages。

在服务器SSH终端执行：

```bash
cd /opt/p4schedule
git fetch origin
git switch --track origin/feature/account-isolation
bash server/deploy_accounts.sh
```

如果已经有本地feature/account-isolation分支，用git switch feature/account-isolation再git pull --ff-only，不要重复创建分支。

部署脚本会停止API、在/root下生成权限600的数据库备份、提示你设置网站账户aiymsore的密码、执行迁移、重启API。过程中短暂停止课表服务。MySQL仍运行。需要当前SSH用户是root（沿用现有环境），数据库root可以通过Unix socket登录。

脚本中不会重设数据库密码，不会删除原课程或上课安排。迁移需要数据库管理员的建表改表权限；schedule_app已有p4schedule.*的SELECT/INSERT/UPDATE/DELETE权限，可操作新增表，不必授予它DDL权限。

迁移失败请保留备份、暂停API并查看错误。MySQL DDL不能整体事务回滚，所以迁移按“可重试、不删除旧数据”设计。请勿直接切回旧单人后端；它不会填写新增的非空schedule_id。

## 服务器验证

打开 https://api.aiymsore.com/ ，它提供本分支的前端；此时GitHub Pages可能仍是旧版本。使用迁移中创建的aiymsore账户登录，确认原170条安排保留。

用无痕窗口注册第二个测试账户，应该只看到空课表。为第二个账户导入后，退出并重新登录aiymsore，确认两个账户课表独立。直接GET /api/courses不带登录凭据应返回401。

验证后将本分支合并到main并推送，Pages部署后从 https://aiymsore.github.io/p4schedule/ 登录。ALLOWED_ORIGINS应继续包含https://aiymsore.github.io；不要加路径。新接口使用Authorization请求头，不再接受UPLOAD_TOKEN作为登录凭据。旧UPLOAD_TOKEN环境变量可移除，但不会被新版本读取。

## 实现边界

- 用户名只接受3至32位英文、数字、下划线，不区分大小写；密码12至128字符，PBKDF2-HMAC-SHA256、随机盐、600000次迭代。
- 不透明随机会话令牌有效24小时；数据库仅存SHA256摘要。浏览器令牌在sessionStorage中保存，退出删除服务器会话并清除屏幕数据。不是HttpOnly cookie，务必保持前端脚本可信，避免引入不可信脚本；不通过网址传递令牌。
- 登录/注册进行数据库持久化限速。限速依赖部署的代理正确提供客户端地址；没有自行读取任意X-Forwarded-For请求头。
- 所有课程查询、上传、清空在后端根据会话user_id检查归属，修改schedule_id不能访问其他用户。没有用户输入SQL拼接。
- 导入与清空共用课表级数据库锁，所有写入统一提交，异常回滚。重复安排跳过；相同名称、教师的课程在不同课表分别存储。
- API响应禁止缓存；退出、切换账户/课表时清屏，旧异步响应不会覆盖新账户数据。取消共享JSON自动回退，公开courses.json替换为空数组；Git历史中的旧公开数据仍存在。
- 每次最多5000条、每份课表容量10000条、上传上限10MB。当前解析器支持1至12连续节次，复杂非连续节次和不同学校版式需进一步适配。

## 测试

```bash
cd /opt/p4schedule/server
../.venv/bin/python -m pytest -q
```

隔离测试使用内存SQLite执行真实查询，通过适配层处理MySQL参数占位符和连接锁，不会读写线上数据库。覆盖双账户、伪造课表编号、相同课程分开存储、空账户、退出撤销、过期会话、密码哈希、导入失败回滚、课表起始日期。

开发时另用独立的MySQL 8.4临时实例验证了真实DDL迁移、重复迁移、170条旧安排保留、受限应用账户权限、双账户导入/清空隔离、重复导入、限速和退出撤销。云服务器为MySQL 8.0，仍需按升级顺序在备份后验证该环境。
