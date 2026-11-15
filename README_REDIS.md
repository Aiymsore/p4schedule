# Redis课表缓存

此分支基于账户隔离版。MySQL仍是正式数据来源，Redis只保存可重建的查询结果。默认未设置REDIS_URL时不启用缓存。网页现有的完整课表查询会缓存；GET /api/courses增加可选week参数，支持真正按周查询与缓存。前端周切换仍在已加载的数据中筛选，不会每次切周都发请求。

## 工作原理

缓存键示例：p4schedule:courses:v1:u:1:s:2:r:3:w:10。
u是用户、s是课表、r是MySQL中的数据版本，w是周次；不传周次则为all。每次读取先用MySQL校验课表归属和版本，命中后省去课程关联查询，不会完全停止访问MySQL。

有效期默认300秒，包括空结果。新增课程或清空课表时，cache_version与数据写入在同一个MySQL事务中更新，之后只读取新版本缓存。旧键由TTL自动清理。仅跳过重复记录、不改变数据时，版本不变。

版本保存在MySQL，避免Redis离线时未删除旧缓存，以及并发旧查询写回覆盖新查询的问题。中途失败回滚时，版本和数据一起回滚。Redis超时、连接失败或缓存损坏时回退MySQL；短连接/读取超时且不重试，日志不打印含密码的Redis连接URL。

## 云服务器安装

在Ubuntu SSH终端执行：

```bash
apt update
apt install -y redis-server
systemctl enable --now redis-server
redis-cli ping
```

应返回PONG。确认Redis仅绑定127.0.0.1/::1、protected-mode为yes。不要开放6379到公网。此服务器只有1GB内存，Redis仅用于本项目缓存时，建议在/etc/redis/redis.conf设置maxmemory 32mb及maxmemory-policy allkeys-lru，再重启redis-server。若已有其他服务使用Redis，不要直接修改它的全局内存或持久化策略。

## 更新账户版

确认账户版已经迁移并正常登录，准备几分钟维护时间。代码不改main，先从独立分支验证。

```bash
cd /opt/p4schedule
git fetch origin
git switch --track origin/feature/redis-cache
.venv/bin/python -m pip install -r server/requirements.txt
systemctl stop p4schedule
umask 077
mysqldump --single-transaction --no-tablespaces p4schedule > /root/p4schedule-before-redis-$(date +%Y%m%d-%H%M%S).sql
.venv/bin/python server/migrate_redis.py
```

每条成功后才执行下一条。若已有feature/redis-cache本地分支，请切换后git pull --ff-only。迁移只增加schedules.cache_version，不删除课表，可重复执行。应用数据库账户只需要原有DML权限，建表改表仍由数据库管理员完成。

编辑/etc/p4schedule.env，保留原配置，加入（已存在时修改原行，避免重复）：

```text
REDIS_URL=redis://127.0.0.1:6379/1
COURSE_CACHE_TTL=300
```

连接Redis逻辑库1；它与MySQL的数据库不是同一个概念。Redis URL若含密码，文件仍应只有root可读，不提交到Git。

```bash
systemctl restart p4schedule
systemctl is-active p4schedule
cd /opt/p4schedule/server
../.venv/bin/python check_cache.py --week 1
```

输入网站账户和密码，脚本会登录并连续查询两次，最后退出会话。第一次通常MISS，第二次HIT；如果别人已查询过，第一次也可能HIT。BYPASS表示未配置Redis或Redis不可用；返回课程仍来自MySQL。不要将令牌或密码发给他人。

导入确实新增课程后再次查询应MISS；重复导入且无新增则保持原缓存。清空会让新结果为空。可以用redis-cli -n 1 --scan --pattern 'p4schedule:courses:v1:*'查看键，用TTL查看剩余秒数，不要FLUSHALL。

## 测试与边界

自动测试覆盖MISS/HIT、TTL过期、按周筛选、空缓存、双账户隔离、越权请求不能读缓存、导入/清空版本失效、Redis故障和损坏缓存回退、失败回滚不改变缓存版本。

缓存测试使用可控的Redis替身，不会连接生产Redis；云端安装后的check_cache.py是实机验收步骤。旧课程库使用外部SQL直接修改时不会自动增加cache_version，此时缓存最多延迟TTL时长；管理员直接改课程后应同时增加相应课表的cache_version，或等待缓存过期。
