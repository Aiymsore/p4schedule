"""账户版迁移完成后，以MySQL管理员执行；可重复运行，不删除数据。"""
import argparse
from getpass import getpass
import pymysql


def migrate(connection):
    with connection.cursor() as cursor:
        cursor.execute("""SELECT COUNT(*) FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='schedules' AND COLUMN_NAME='cache_version'""")
        if not cursor.fetchone()[0]:
            cursor.execute("ALTER TABLE schedules ADD COLUMN cache_version BIGINT UNSIGNED NOT NULL DEFAULT 1")
    connection.commit()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tcp", action="store_true")
    parser.add_argument("--port", type=int, default=3306)
    args = parser.parse_args()
    options = dict(user="root", database="p4schedule", charset="utf8mb4")
    if args.tcp:
        options.update(host="127.0.0.1", port=args.port, password=getpass("MySQL管理员密码："))
    else:
        options["unix_socket"] = "/var/run/mysqld/mysqld.sock"
    connection = pymysql.connect(**options)
    try:
        migrate(connection)
        print("缓存版本字段已就绪，课表记录保持不变。")
    finally:
        connection.close()
