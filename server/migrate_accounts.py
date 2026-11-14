"""先备份数据库、停止API，再用数据库管理员运行。可重复执行，不删除旧课表。"""
import argparse
from datetime import date
from getpass import getpass
import pymysql

from schema_accounts import ACCOUNT_TABLES
from security import hash_password, normalize_username, verify_password


def migrate(connection, username, password, start):
    if start.weekday() != 0:
        raise ValueError("学期起点必须是第一周周一")
    encoded = hash_password(password)
    with connection.cursor() as cursor:
        cursor.execute("SELECT GET_LOCK('p4schedule.account_migration',10)")
        if cursor.fetchone()[0] != 1:
            raise RuntimeError("已有迁移在运行")
        for ddl in ACCOUNT_TABLES:
            cursor.execute(ddl)
        cursor.execute("""SELECT COUNT(*) FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='courses' AND COLUMN_NAME='schedule_id'""")
        if not cursor.fetchone()[0]:
            cursor.execute("ALTER TABLE courses ADD COLUMN schedule_id INT UNSIGNED NULL")
        # DDL可能隐式提交；迁移失败后保留新增结构，下次可安全重试。
        cursor.execute("SELECT id,password_hash FROM users WHERE username=%s", (username,))
        owner = cursor.fetchone()
        if owner:
            if not verify_password(password, owner[1]):
                raise ValueError("此账户已存在，请输入它原来的账户密码；迁移不会重设密码")
            user_id = owner[0]
        else:
            cursor.execute("INSERT INTO users (username,password_hash) VALUES (%s,%s)", (username, encoded))
            user_id = cursor.lastrowid
        cursor.execute("SELECT id FROM schedules WHERE user_id=%s AND label=%s", (user_id, "原有课表"))
        schedule = cursor.fetchone()
        if schedule:
            schedule_id = schedule[0]
        else:
            cursor.execute("INSERT INTO schedules (user_id,label,semester_start) VALUES (%s,%s,%s)",
                           (user_id, "原有课表", start))
            schedule_id = cursor.lastrowid
        cursor.execute("UPDATE courses SET schedule_id=%s WHERE schedule_id IS NULL", (schedule_id,))
        assigned = cursor.rowcount
        connection.commit()
        cursor.execute("ALTER TABLE courses MODIFY schedule_id INT UNSIGNED NOT NULL")
        cursor.execute("""SELECT COUNT(*) FROM information_schema.KEY_COLUMN_USAGE
            WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='courses'
            AND COLUMN_NAME='schedule_id' AND REFERENCED_TABLE_NAME='schedules'""")
        if not cursor.fetchone()[0]:
            cursor.execute("ALTER TABLE courses ADD CONSTRAINT fk_courses_schedule FOREIGN KEY (schedule_id) REFERENCES schedules(id)")
        connection.commit()
    return assigned


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner", default="aiymsore")
    parser.add_argument("--semester-start", default="2026-09-07")
    parser.add_argument("--db-user", default="root")
    parser.add_argument("--socket", default="/var/run/mysqld/mysqld.sock")
    parser.add_argument("--tcp", action="store_true", help="不用本地socket，改用TCP并提示管理员数据库密码")
    args = parser.parse_args()
    username = normalize_username(args.owner)
    password = getpass(f"为课表网站账户 {username} 设置密码（12至128字符，不是数据库密码）：")
    if password != getpass("再次输入账户密码："):
        raise SystemExit("两次密码不同，未执行迁移")
    options = dict(user=args.db_user, database="p4schedule", charset="utf8mb4", autocommit=False)
    if args.tcp:
        options.update(host="127.0.0.1", password=getpass("数据库管理员密码："))
    else:
        options["unix_socket"] = args.socket
    connection = pymysql.connect(**options)
    try:
        count = migrate(connection, username, password, date.fromisoformat(args.semester_start))
        print(f"迁移成功，{count}条课程归属到 {username} 的原有课表。旧上课记录已保留。")
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
