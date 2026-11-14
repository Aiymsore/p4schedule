"""单人单学期课表，追加导入、完整安排去重。"""
import os
import re
from datetime import date
import pymysql


def connect():
    return pymysql.connect(
        host="127.0.0.1", port=3306, user="schedule_app",
        password=os.environ["SCHEDULE_DB_PASSWORD"], database="p4schedule",
        charset="utf8mb4", autocommit=False, connect_timeout=5,
        read_timeout=30, write_timeout=30, cursorclass=pymysql.cursors.DictCursor,
    )


def read_courses():
    connection = connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute("""SELECT s.id, c.name, c.teacher, s.class_date,
                s.start_period, s.end_period, s.location
                FROM courses c JOIN course_sessions s ON c.id=s.course_id
                ORDER BY s.class_date, s.start_period, s.id""")
            rows = cursor.fetchall()
        start = date.fromisoformat(os.environ.get("SEMESTER_START", "2026-09-07"))
        entries = []
        for row in rows:
            day = row["class_date"]
            if isinstance(day, str):
                day = date.fromisoformat(day)
            match = re.fullmatch(r"(.*?)\[([^\]]+)\]", row["name"])
            periods = list(range(row["start_period"], row["end_period"] + 1))
            week = (day - start).days // 7 + 1
            entries.append({
                "week": week, "date": day.isoformat(), "weekday": day.isoweekday(),
                "weekday_name": ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][day.weekday()],
                "course": match[1] if match else row["name"],
                "course_type": match[2] if match else "理论课时",
                "teacher": row["teacher"] or "", "location": row["location"] or "",
                "periods": periods, "period_code": f"{periods[0]:02d}{periods[-1]:02d}",
                "source_week": week, "big_sections": sorted({(p + 1) // 2 for p in periods}),
            })
        return entries
    finally:
        connection.close()


def import_courses(entries):
    if not entries:
        raise ValueError("没有可导入的课程")
    records = set()
    for item in entries:
        name = item["course"] + (f"[{item['course_type']}]" if item.get("course_type") else "")
        teacher, location = item["teacher"], item["location"]
        if not name or any(not isinstance(s, str) or len(s) > 100 for s in (name, teacher, location)):
            raise ValueError("课程、教师或教室字段不符合数据库要求（最多100字符）")
        day = date.fromisoformat(item["date"])
        periods = item["periods"]
        if (not periods or any(type(p) is not int for p in periods)
                or periods != list(range(periods[0], periods[-1] + 1))
                or not 1 <= periods[0] <= periods[-1] <= 12):
            raise ValueError("节次必须是1至12节内的连续节次")
        records.add((name, teacher, day, periods[0], periods[-1], location))
    connection = connect()
    added = skipped = 0
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT GET_LOCK('p4schedule.web_import', 10) AS acquired")
            if cursor.fetchone()["acquired"] != 1:
                raise ValueError("其他导入正在进行，请稍后重试")
            ids = {}
            for name, teacher, day, first, last, location in sorted(records):
                key = (name, teacher)
                if key not in ids:
                    cursor.execute("SELECT id FROM courses WHERE name=%s AND teacher=%s", key)
                    matches = cursor.fetchall()
                    if len(matches) > 1:
                        raise ValueError("数据库存在同名同教师的重复课程，请先核对")
                    if matches:
                        ids[key] = matches[0]["id"]
                    else:
                        cursor.execute("INSERT INTO courses (name, teacher) VALUES (%s,%s)", key)
                        ids[key] = cursor.lastrowid
                values = (ids[key], day, first, last, location)
                cursor.execute("""SELECT id FROM course_sessions WHERE course_id=%s
                    AND class_date=%s AND start_period=%s AND end_period=%s
                    AND location=%s LIMIT 1""", values)
                if cursor.fetchone():
                    skipped += 1
                else:
                    cursor.execute("""INSERT INTO course_sessions
                        (course_id,class_date,start_period,end_period,location)
                        VALUES (%s,%s,%s,%s,%s)""", values)
                    added += 1
        connection.commit()
        return {"parsed_count": len(records), "added": added, "skipped": skipped}
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()  # 同时释放连接级的GET_LOCK
