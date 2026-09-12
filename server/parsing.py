"""自适应课表解析：xlsx / xls / docx → 现有 courses.json 的 12 字段 schema。

设计要点：
- 无需真实样例，靠表头关键词评分定位表头行；新格式只需在 COLUMN_ALIASES 里加别名。
- 课程名 / 教师名保持原文不改写：前端翘课指数的存储键是 `course__teacher`。
"""

from __future__ import annotations

import os
import re
from datetime import date, timedelta
from typing import Any, Iterable

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

SEMESTER_START = os.environ.get("SEMESTER_START", "2026-09-07")
DEFAULT_COURSE_TYPE = "理论课时"
WEEKDAY_NAMES = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

# 每个逻辑字段的候选表头关键词（按优先级），命中即得分
COLUMN_ALIASES: dict[str, list[str]] = {
    "course": ["课程", "课名", "课程名称", "课程名"],
    "teacher": ["教师", "老师", "授课教师", "任课教师", "主讲"],
    "weekday": ["星期", "周几", "周次名称", "上课星期", "星期几"],
    "weeks": ["周次", "上课周次", "周数", "起止周"],
    "periods": ["节次", "时间", "上课节次", "节", "时段"],
    "location": ["地点", "教室", "上课地点", "位置"],
    "course_type": ["课程类型", "课型", "性质", "课程性质"],
    "date": ["日期", "上课日期"],
}

WEEKDAY_CHAR_TO_NUMBER = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "日": 7, "天": 7}


class ParseError(ValueError):
    """解析失败，信息直接展示给用户。"""


# ---------------------------------------------------------------------------
# 表头定位与列映射
# ---------------------------------------------------------------------------

def find_header_row(rows: list[list[Any]]) -> tuple[int, dict[str, int]]:
    """在前若干行里找表头行，返回 (行号, {字段名: 列号})。"""
    best_row, best_map, best_score = -1, {}, 0.0

    for row_index, row in enumerate(rows[:25]):
        cells = [str(cell).strip() if cell is not None else "" for cell in row]
        mapping: dict[str, int] = {}
        score = 0.0

        for field, aliases in COLUMN_ALIASES.items():
            for col_index, cell in enumerate(cells):
                if any(alias in cell for alias in aliases):
                    # 短列名（如"节次"）比长串（如"上课时间地点"）更可信
                    mapping.setdefault(field, col_index)
                    score += 1
                    break

        # 课程 + (星期或周次或节次) 是最低可用标准
        if score > best_score and "course" in mapping:
            best_row, best_map, best_score = row_index, mapping, score

    if best_row < 0 or not {"weekday", "weeks", "periods"} & best_map.keys():
        raise ParseError("未能识别表头行：文件中需要包含『课程』列和『星期/周次/节次』中的至少一列。")

    return best_row, best_map


# ---------------------------------------------------------------------------
# 单元格取值
# ---------------------------------------------------------------------------

def cell_text(row: list[Any], col: int | None) -> str:
    if col is None or col >= len(row):
        return ""
    value = row[col]
    if value is None:
        return ""
    return str(value).strip()


# ---------------------------------------------------------------------------
# 各字段解析
# ---------------------------------------------------------------------------

def parse_weekday(text: str) -> int | None:
    """"周一 / 星期三 / 周七 / 3" → 1..7。"""
    cleaned = text.strip()
    if not cleaned:
        return None

    for char in cleaned:
        if char in WEEKDAY_CHAR_TO_NUMBER:
            return WEEKDAY_CHAR_TO_NUMBER[char]

    match = re.search(r"\d+", cleaned)
    if match:
        number = int(match.group())
        if 1 <= number <= 7:
            return number

    return None


def parse_weeks(text: str) -> list[int]:
    """"1-16周" / "1,3,5周" / "1-15单周" / "2-16双周" / "第3周" → 周数列表。"""
    cleaned = text.replace("，", ",").replace(" ", "")
    if not cleaned:
        return []

    odd = "单" in cleaned
    even = "双" in cleaned
    weeks: list[int] = []

    for part in cleaned.split(","):
        match = re.search(r"(\d+)\s*[-—~至]\s*(\d+)", part)
        if match:
            start, end = int(match.group(1)), int(match.group(2))
            weeks.extend(range(start, end + 1))
            continue

        match = re.search(r"\d+", part)
        if match:
            weeks.append(int(match.group()))

    if odd:
        weeks = [week for week in weeks if week % 2 == 1]
    elif even:
        weeks = [week for week in weeks if week % 2 == 0]

    return sorted({week for week in weeks if 1 <= week <= 30})


def parse_periods(text: str) -> list[int]:
    """"0102" / "0304" / "1-2节" / "第1,2节" / "9-10" → 节次列表。"""
    cleaned = text.replace("，", ",").replace(" ", "").replace("节", "")

    # 连写形式：0102 → [1,2]，12 → [1,2]
    compact = re.fullmatch(r"(\d{2})(\d{2})", cleaned)
    if compact:
        return sorted({int(compact.group(1)), int(compact.group(2))})

    compact = re.fullmatch(r"(\d)(\d)", cleaned)
    if compact:
        return sorted({int(compact.group(1)), int(compact.group(2))})

    periods: list[int] = []
    for part in cleaned.split(","):
        match = re.search(r"(\d+)\s*[-—~至]\s*(\d+)", part)
        if match:
            start, end = int(match.group(1)), int(match.group(2))
            periods.extend(range(start, end + 1))
            continue

        match = re.search(r"\d+", part)
        if match:
            periods.append(int(match.group()))

    return sorted({period for period in periods if 1 <= period <= 12})


def derive_date(week: int, semester_start: date) -> str:
    return (semester_start + timedelta(days=(week - 1) * 7)).isoformat()


def derive_big_sections(periods: list[int]) -> list[int]:
    return sorted({(period + 1) // 2 for period in periods})


# ---------------------------------------------------------------------------
# 行 → 条目
# ---------------------------------------------------------------------------

def rows_to_entries(
    rows: list[list[Any]],
    semester_start: date | None = None,
) -> list[dict]:
    """把整张表（含表头）转为 courses.json 同构条目列表。"""
    header_row, mapping = find_header_row(rows)
    semester_start = semester_start or date.fromisoformat(SEMESTER_START)
    entries: list[dict] = []

    for row in rows[header_row + 1:]:
        course = cell_text(row, mapping.get("course"))
        if not course:
            continue

        teacher = cell_text(row, mapping.get("teacher"))
        location = cell_text(row, mapping.get("location"))
        course_type = cell_text(row, mapping.get("course_type")) or DEFAULT_COURSE_TYPE

        weekday = parse_weekday(cell_text(row, mapping.get("weekday")))
        periods = parse_periods(cell_text(row, mapping.get("periods")))
        weeks = parse_weeks(cell_text(row, mapping.get("weeks")))

        if weekday is None and periods and "weekday" not in mapping:
            raise ParseError("缺少『星期』列且无法推断上课日，请检查文件。")
        if weekday is None:
            weekday = 1
        if not periods:
            periods = [1]
        if not weeks:
            weeks = [1]

        for week in weeks:
            entries.append(
                {
                    "week": week,
                    "date": derive_date(week, semester_start),
                    "weekday": weekday,
                    "weekday_name": WEEKDAY_NAMES[weekday - 1],
                    "course": course,
                    "course_type": course_type,
                    "teacher": teacher,
                    "period_code": f"{periods[0]:02d}{periods[-1]:02d}",
                    "periods": periods,
                    "location": location,
                    "source_week": week,
                    "big_sections": derive_big_sections(periods),
                }
            )

    if not entries:
        raise ParseError("表中没有解析出任何课程行（第一列需要是课程名）。")

    return entries


# ---------------------------------------------------------------------------
# 文件级入口
# ---------------------------------------------------------------------------

def parse_xlsx(data: bytes, extension: str = ".xlsx") -> list[dict]:
    from io import BytesIO

    all_entries: list[dict] = []

    if extension == ".xls":
        import xlrd

        # 老式 .xls 用 xlrd 直接读（openpyxl 不支持该格式）
        book = xlrd.open_workbook(file_contents=data)
        for sheet in book.sheets():
            rows = [sheet.row_values(row_index) for row_index in range(sheet.nrows)]
            if rows:
                all_entries.extend(rows_to_entries(rows))
    else:
        from openpyxl import load_workbook

        workbook = load_workbook(BytesIO(data), data_only=True, read_only=True)
        for worksheet in workbook.worksheets:
            rows = [list(row) for row in worksheet.iter_rows(values_only=True)]
            if rows:
                all_entries.extend(rows_to_entries(rows))
        workbook.close()

    if not all_entries:
        raise ParseError("工作簿中没有可用数据。")
    return all_entries


def parse_docx(data: bytes) -> list[dict]:
    from docx import Document
    from io import BytesIO

    document = Document(BytesIO(data))
    all_entries: list[dict] = []

    for table in document.tables:
        rows = [[cell.text for cell in row.cells] for row in table.rows]
        if rows:
            all_entries.extend(rows_to_entries(rows))

    if not all_entries:
        raise ParseError("Word 文档中没有可识别的表格，请使用表格形式的课表。")
    return all_entries


def parse_file(filename: str, data: bytes) -> list[dict]:
    extension = os.path.splitext(filename)[1].lower()

    if extension in (".xlsx", ".xls"):
        return parse_xlsx(data, extension)
    if extension == ".docx":
        return parse_docx(data)

    raise ParseError(f"暂不支持 {extension or '该'} 格式，请上传 xlsx / xls / docx 文件。")
