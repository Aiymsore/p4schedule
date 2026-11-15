"""按登录用户和课表隔离读写。所有归属检查均在服务器执行。"""
import os
import re
from datetime import date, timedelta
import pymysql
import course_cache


class ScheduleNotFound(Exception):
    pass


def semester_start():
    return date.fromisoformat(os.environ.get("SEMESTER_START", "2026-09-07"))


def connect():
    return pymysql.connect(
        host="127.0.0.1", port=3306, user="schedule_app",
        password=os.environ["SCHEDULE_DB_PASSWORD"], database="p4schedule",
        charset="utf8mb4", autocommit=False, connect_timeout=5,
        read_timeout=30, write_timeout=30, cursorclass=pymysql.cursors.DictCursor,
    )


def owned_schedule(cursor, user_id, schedule_id):
    if schedule_id is None:
        cursor.execute("SELECT id,label,semester_start,cache_version FROM schedules WHERE user_id=%s ORDER BY id LIMIT 1", (user_id,))
    else:
        cursor.execute("SELECT id,label,semester_start,cache_version FROM schedules WHERE id=%s AND user_id=%s", (schedule_id, user_id))
    row = cursor.fetchone()
    if not row:
        raise ScheduleNotFound()
    if isinstance(row["semester_start"], str):
        row["semester_start"] = date.fromisoformat(row["semester_start"])
    return row


def list_schedules(user_id):
    connection = connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT id,label,semester_start FROM schedules WHERE user_id=%s ORDER BY id", (user_id,))
            return cursor.fetchall()
    finally:
        connection.close()


def create_schedule(user_id, label, start):
    connection = connect()
    try:
        with connection.cursor() as cursor:
            # 序列化同一用户的创建，限制每账户课表数，防止无限增长。
            cursor.execute("SELECT id FROM users WHERE id=%s FOR UPDATE", (user_id,))
            cursor.fetchone()
            cursor.execute("SELECT COUNT(*) AS total FROM schedules WHERE user_id=%s", (user_id,))
            if cursor.fetchone()["total"] >= 12:
                raise ValueError("每个账户最多创建12份课表")
            cursor.execute("INSERT INTO schedules (user_id,label,semester_start) VALUES (%s,%s,%s)", (user_id,label,start))
            schedule_id = cursor.lastrowid
        connection.commit()
        return {"id": schedule_id, "label": label, "semester_start": start}
    except pymysql.IntegrityError as error:
        connection.rollback()
        if error.args[0] == 1062:
            raise ValueError("你已有同名课表，请换一个名称") from error
        raise
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def read_courses(user_id, schedule_id=None, week=None, cache_info=None):
    if week is not None and (type(week) is not int or not 1 <= week <= 60):
        raise ValueError("周次需为1至60")
    connection = connect()
    try:
        with connection.cursor() as cursor:
            schedule = owned_schedule(cursor, user_id, schedule_id)
            # 即使命中缓存，也先向MySQL确认归属与最新版本，不能绕过授权。
            cache_key = course_cache.key(user_id, schedule["id"], schedule["cache_version"], week)
            cached, state = course_cache.read(cache_key)
            if cache_info is not None:
                cache_info["status"] = state
            if cached is not None:
                return cached
            sql = """SELECT s.id, c.name, c.teacher, s.class_date,
                s.start_period, s.end_period, s.location
                FROM courses c JOIN course_sessions s ON c.id=s.course_id
                JOIN schedules t ON t.id=c.schedule_id
                WHERE t.id=%s AND t.user_id=%s
            """
            params = [schedule["id"], user_id]
            if week is not None:
                first = schedule["semester_start"] + timedelta(weeks=week - 1)
                sql += " AND s.class_date >= %s AND s.class_date < %s"
                params.extend([first, first + timedelta(days=7)])
            sql += " ORDER BY s.class_date, s.start_period, s.id"
            cursor.execute(sql, tuple(params))
            rows = cursor.fetchall()
        start = schedule["semester_start"]
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
                "weekday_name": ["周一","周二","周三","周四","周五","周六","周日"][day.weekday()],
                "course": match[1] if match else row["name"],
                "course_type": match[2] if match else "理论课时",
                "teacher": row["teacher"] or "", "location": row["location"] or "",
                "periods": periods, "period_code": f"{periods[0]:02d}{periods[-1]:02d}",
                "source_week": week, "big_sections": sorted({(p+1)//2 for p in periods}),
            })
        # 同一次MySQL快照下读取的旧数据只会写到旧版本键，不覆盖新版本。
        if state != "BYPASS" and not course_cache.write(cache_key, entries) and cache_info is not None:
            cache_info["status"] = "BYPASS"
        return entries
    finally:
        connection.close()


def validate_entries(entries):
    if not entries or len(entries)>5000:
        raise ValueError("每次需导入1至5000条安排")
    records = set()
    for item in entries:
        name = item["course"] + (f"[{item['course_type']}]" if item.get("course_type") else "")
        teacher, location = item["teacher"], item["location"]
        if not name or any(not isinstance(s,str) or len(s)>100 for s in (name,teacher,location)):
            raise ValueError("课程、教师或教室字段最多100字符，课程名不能为空")
        day = date.fromisoformat(item["date"])
        periods = item["periods"]
        if (not periods or any(type(p)is not int for p in periods)
            or periods!=list(range(periods[0],periods[-1]+1))
            or not 1<=periods[0]<=periods[-1]<=12):
            raise ValueError("节次必须是1至12节内的连续节次")
        records.add((name,teacher,day,periods[0],periods[-1],location))
    return records


def lock_schedule(cursor, schedule_id):
    cursor.execute("SELECT GET_LOCK(%s,10) AS acquired", (f"p4schedule.import.{schedule_id}",))
    if cursor.fetchone()["acquired"]!=1:
        raise ValueError("此课表正在更新，请稍后重试")


def import_courses(entries, user_id, schedule_id):
    records = validate_entries(entries)
    connection = connect()
    added = skipped = 0
    try:
        with connection.cursor() as cursor:
            schedule = owned_schedule(cursor,user_id,schedule_id)
            # 结束归属检查建立的旧快照，拿到锁后再读取最新导入结果。
            connection.commit()
            lock_schedule(cursor,schedule["id"])
            # 防止登录用户无限追加；当前学习版每份课表最多10000条。
            cursor.execute("""SELECT COUNT(*) AS total FROM course_sessions s
                JOIN courses c ON c.id=s.course_id WHERE c.schedule_id=%s""",(schedule["id"],))
            if cursor.fetchone()["total"]+len(records)>10000:
                raise ValueError("此课表接近容量上限，请先整理数据或新建课表")
            ids = {}
            for name,teacher,day,first,last,location in sorted(records):
                key=(name,teacher)
                if key not in ids:
                    cursor.execute("SELECT id FROM courses WHERE schedule_id=%s AND name=%s AND teacher=%s",
                                   (schedule["id"],name,teacher))
                    matches=cursor.fetchall()
                    if len(matches)>1:
                        raise ValueError("此课表存在同名同教师的重复课程，请先核对")
                    if matches:
                        ids[key]=matches[0]["id"]
                    else:
                        cursor.execute("INSERT INTO courses (schedule_id,name,teacher) VALUES (%s,%s,%s)",
                                       (schedule["id"],name,teacher))
                        ids[key]=cursor.lastrowid
                values=(ids[key],day,first,last,location)
                cursor.execute("""SELECT id FROM course_sessions WHERE course_id=%s
                    AND class_date=%s AND start_period=%s AND end_period=%s
                    AND location=%s LIMIT 1""",values)
                if cursor.fetchone():
                    skipped+=1
                else:
                    cursor.execute("""INSERT INTO course_sessions
                        (course_id,class_date,start_period,end_period,location)
                        VALUES (%s,%s,%s,%s,%s)""",values)
                    added+=1
            if added:
                cursor.execute("UPDATE schedules SET cache_version=cache_version+1 WHERE id=%s AND user_id=%s",
                               (schedule["id"], user_id))
        connection.commit()
        return {"parsed_count":len(records),"added":added,"skipped":skipped}
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def clear_schedule(user_id,schedule_id):
    connection=connect()
    try:
        with connection.cursor() as cursor:
            schedule=owned_schedule(cursor,user_id,schedule_id)
            connection.commit()
            lock_schedule(cursor,schedule["id"])
            cursor.execute("""DELETE FROM course_sessions WHERE course_id IN
                (SELECT id FROM courses WHERE schedule_id=%s)""",(schedule["id"],))
            deleted=cursor.rowcount
            cursor.execute("DELETE FROM courses WHERE schedule_id=%s",(schedule["id"],))
            cursor.execute("UPDATE schedules SET cache_version=cache_version+1 WHERE id=%s AND user_id=%s",
                           (schedule["id"], user_id))
        connection.commit()
        return {"deleted":deleted}
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
