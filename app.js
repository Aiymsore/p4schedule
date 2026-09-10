/*
  app.js

  当前数据流程：

  courses.json
      ↓ fetch()
  JavaScript 对象
      ↓
  renderBaseGrid()
      ↓
  renderCourses()
      ↓
  HTML 页面

  后续 Python 生成 schedule.json 后，
  主要修改 loadCourses() 和数据字段映射即可。
*/


const DAYS = [
  "周一",
  "周二",
  "周三",
  "周四",
  "周五",
  "周六",
  "周日"
];

const TOTAL_SECTIONS = 12;

const scheduleGrid = document.getElementById("scheduleGrid");

// =========================================================
// 课程详情 DOM
// =========================================================

const courseModal =
  document.getElementById("courseModal");

const closeCourseModalButton =
  document.getElementById("closeCourseModal");

const courseModalBackdrop =
  document.querySelector(".course-modal-backdrop");


const detailCourseName =
  document.getElementById("detailCourseName");

const detailTeacher =
  document.getElementById("detailTeacher");

const detailLocation =
  document.getElementById("detailLocation");

const detailTime =
  document.getElementById("detailTime");

const detailDate =
  document.getElementById("detailDate");

const detailCourseType =
  document.getElementById("detailCourseType");


// =========================================================
// 翘课指数 DOM
// =========================================================

const skipResult =
  document.getElementById("skipResult");

const skipScore =
  document.getElementById("skipScore");

const skipLevel =
  document.getElementById("skipLevel");

const skipEvaluatedTime =
  document.getElementById("skipEvaluatedTime");

const skipQuestionnaire =
  document.getElementById("skipQuestionnaire");

const retestSkipIndexButton =
  document.getElementById("retestSkipIndex");

const simulateSkipResultButton =
  document.getElementById("simulateSkipResult");


// 当前详情页正在查看哪一门课
let activeCourse = null;


// localStorage 使用的键名
const SKIP_INDEX_STORAGE_KEY =
  "p4schedule_skip_index";

// 保存全部课程
let allCourses = [];

// 当前显示第几周
let currentWeek = 1;

// 最大周数
let maxWeek = 1;


// 获取 HTML 中的周数切换器
const prevWeekButton = document.getElementById("prevWeek");
const nextWeekButton = document.getElementById("nextWeek");
const weekLabel = document.getElementById("weekLabel");


/**
 * 读取 JSON 数据。
 *
 * 后续可以把：
 *   fetch("./courses.json")
 *
 * 改成：
 *   fetch("./schedule.json")
 *
 * 或改成真正的后端 API：
 *   fetch("/api/schedule")
 */
async function loadCourses() {
  const response = await fetch("./courses.json");

  if (!response.ok) {
    throw new Error(`课程数据读取失败：${response.status}`);
  }

  return await response.json();
}


/**
 * 先创建一个完全空白的课表。
 */
function renderBaseGrid() {
  // 左上角
  const corner = document.createElement("div");
  corner.className = "grid-cell corner-cell";
  corner.textContent = "节次";
  scheduleGrid.appendChild(corner);

  // 周一 ~ 周日
  DAYS.forEach(day => {
    const header = document.createElement("div");
    header.className = "grid-cell day-header";
    header.textContent = day;
    scheduleGrid.appendChild(header);
  });

  // 第 1 ~ 12 节
  for (let section = 1; section <= TOTAL_SECTIONS; section++) {
    const sectionLabel = document.createElement("div");
    sectionLabel.className = "grid-cell section-label";
    sectionLabel.textContent = `第 ${section} 节`;
    scheduleGrid.appendChild(sectionLabel);

    // 每节课后面建立 7 个空白星期格
    for (let weekday = 1; weekday <= 7; weekday++) {
      const cell = document.createElement("div");

      cell.className = "grid-cell";
      cell.dataset.weekday = weekday;
      cell.dataset.section = section;

      scheduleGrid.appendChild(cell);
    }
  }
}

/**
 * 为每一门课生成一个稳定 ID。
 *
 * 当前规则：
 * 课程名 + 教师
 *
 * 所以不同周的同一门课会共享一个翘课指数。
 */
function getCourseId(course) {

  return `${course.course}__${course.teacher}`;

}


/**
 * 读取全部翘课指数。
 */
function getAllSkipResults() {

  const rawData =
    localStorage.getItem(SKIP_INDEX_STORAGE_KEY);

  if (!rawData) {
    return {};
  }

  try {

    return JSON.parse(rawData);

  } catch (error) {

    console.error("翘课指数数据读取失败：", error);

    return {};
  }

}


/**
 * 读取某一门课的翘课指数。
 */
function getSkipResult(course) {

  const results = getAllSkipResults();

  const courseId = getCourseId(course);

  return results[courseId] || null;

}


/**
 * 保存某一门课的翘课指数。
 */
function saveSkipResult(course, result) {

  const results = getAllSkipResults();

  const courseId = getCourseId(course);

  results[courseId] = result;

  localStorage.setItem(
    SKIP_INDEX_STORAGE_KEY,
    JSON.stringify(results)
  );

}

function getSkipLevel(score) {

  if (score <= 20) {
    return "强烈不建议翘";
  }

  if (score <= 40) {
    return "不太建议翘";
  }

  if (score <= 60) {
    return "看情况";
  }

  if (score <= 80) {
    return "比较适合翘";
  }

  return "翘课指数很高";

}

/**
 * 把已有评分显示出来。
 */
function showSkipResult(result) {

  skipResult.classList.remove("hidden");

  skipScore.textContent = result.score;

  skipLevel.textContent = result.level;


  if (result.updatedAt) {

    const date =
      new Date(result.updatedAt);

    skipEvaluatedTime.textContent =
      `上次评估：${date.toLocaleString()}`;

  } else {

    skipEvaluatedTime.textContent = "";

  }

}


/**
 * 打开一门课程的详情页。
 */
function openCourseDetail(course) {

  activeCourse = course;


  // -------------------------
  // 填课程基本信息
  // -------------------------

  detailCourseName.textContent =
    course.course;

  detailTeacher.textContent =
    course.teacher;

  detailLocation.textContent =
    course.location;

  detailDate.textContent =
    course.date;

  detailCourseType.textContent =
    course.course_type;


  const startSection =
    course.periods[0];

  const endSection =
    course.periods[
      course.periods.length - 1
    ];

  detailTime.textContent =
    `${course.weekday_name} 第 ${startSection}–${endSection} 节`;


  // -------------------------
  // 判断有没有历史评分
  // -------------------------

  const result =
    getSkipResult(course);


  if (result) {

    // 有评分

    showSkipResult(result);

    skipQuestionnaire
      .classList
      .add("hidden");

    retestSkipIndexButton
      .classList
      .remove("hidden");

  } else {

    // 没有评分

    skipResult
      .classList
      .add("hidden");

    skipQuestionnaire
      .classList
      .remove("hidden");

    retestSkipIndexButton
      .classList
      .add("hidden");

  }


  // 最后才打开弹窗

  courseModal
    .classList
    .remove("hidden");

  courseModal
    .setAttribute(
      "aria-hidden",
      "false"
    );

}


/**
 * 关闭课程详情。
 */
function closeCourseDetail() {

  courseModal
    .classList
    .add("hidden");

  courseModal
    .setAttribute(
      "aria-hidden",
      "true"
    );

  activeCourse = null;

}

closeCourseModalButton
  .addEventListener(
    "click",
    closeCourseDetail
  );


courseModalBackdrop
  .addEventListener(
    "click",
    closeCourseDetail
  );

document.addEventListener(
  "keydown",
  event => {

    if (
      event.key === "Escape" &&
      !courseModal.classList.contains("hidden")
    ) {

      closeCourseDetail();

    }

  }
);

retestSkipIndexButton
  .addEventListener(
    "click",
    () => {

      // 保留旧结果
      // 只把问卷重新展开

      skipQuestionnaire
        .classList
        .remove("hidden");

      retestSkipIndexButton
        .classList
        .add("hidden");

    }
  );

  simulateSkipResultButton
  .addEventListener(
    "click",
    () => {

      if (!activeCourse) {
        return;
      }


      // 目前固定模拟 78 分
      const score = 78;


      const result = {

        score: score,

        level:
          getSkipLevel(score),

        updatedAt:
          new Date().toISOString()

      };


      // 保存
      saveSkipResult(
        activeCourse,
        result
      );


      // 显示结果
      showSkipResult(result);


      // 收起问卷
      skipQuestionnaire
        .classList
        .add("hidden");


      // 显示重新评估按钮
      retestSkipIndexButton
        .classList
        .remove("hidden");


      // 重新画当前课表
      // 这样小卡片马上出现指数
      renderCurrentWeek();

    }
  );



/**
 * 将 JSON 中的一门课程变成一个课程卡片。
 *
 * CSS Grid 坐标：
 *
 * 第1列：节次
 * 第2列：周一
 * 第3列：周二
 * ...
 *
 * 第1行：星期表头
 * 第2行：第1节
 * 第3行：第2节
 * ...
 */
function createCourseCard(course) {
  const card = document.createElement("article");
  card.className = "course-card";
  card.addEventListener(
  "click",
  () => {

    openCourseDetail(course);

  }
);

  // 星期
  card.style.gridColumn = course.weekday + 1;

  // periods 例如 [1, 2]、[5, 6, 7, 8]
  const startSection = course.periods[0];
  const endSection = course.periods[course.periods.length - 1];

  // 第1节实际上位于 Grid 第2行
  const startRow = startSection + 1;

  // 计算课程跨多少节
  const span = endSection - startSection + 1;

  card.style.gridRow = `${startRow} / span ${span}`;

  const savedSkipResult =
  getSkipResult(course);


let skipIndexHTML = "";


if (savedSkipResult) {

  skipIndexHTML = `
    <div class="course-skip-index">
      翘课指数 ${savedSkipResult.score}
    </div>
  `;

}


card.innerHTML = `

  <div class="course-name">
    ${course.course}
  </div>

  <div class="course-meta">
    ${course.teacher}
  </div>

  <div class="course-meta">
    ${course.location}
  </div>

  <div class="course-meta">
    第 ${startSection}–${endSection} 节
  </div>

  ${skipIndexHTML}

`;

  return card;
}

// 把多门课程依次添加到课表中
function renderCourses(courses) {

  courses.forEach(course => {

    // 先把一条课程数据变成课程卡片
    const card = createCourseCard(course);

    // 再把课程卡片放进课表
    scheduleGrid.appendChild(card);

  });
}

function clearCourseCards() {

  const cards = document.querySelectorAll(".course-card");

  cards.forEach(card => {
    card.remove();
  });

}

function calculateCurrentWeek() {
  // 本学期第 1 周周一
  const semesterStart = new Date(2026, 8, 7);

  // 今天
  const today = new Date();

  // 都设置成当天 0 点，避免小时影响计算
  semesterStart.setHours(0, 0, 0, 0);
  today.setHours(0, 0, 0, 0);

  // 相差多少毫秒
  const diffTime = today - semesterStart;

  // 转换成天数
  const diffDays = Math.floor(
    diffTime / (1000 * 60 * 60 * 24)
  );

  // 算当前第几周
  const week = Math.floor(diffDays / 7) + 1;

  // 防止超出范围
  if (week < 1) {
    return 1;
  }

  if (week > maxWeek) {
    return maxWeek;
  }

  return week;
}

function renderCurrentWeek() {

  // 先删除上一周的课程
  clearCourseCards();

  // 从全部课程里筛选当前周
  const weekCourses = allCourses.filter(course => {
    return course.week === currentWeek;
  });

  // 更新页面上的周数文字
  weekLabel.textContent = `第 ${currentWeek} 周`;

  // 把当前周课程画出来
  renderCourses(weekCourses);

}

// 点击“上一周”
prevWeekButton.addEventListener("click", () => {

  if (currentWeek > 1) {

    currentWeek--;

    renderCurrentWeek();

  }

});


// 点击“下一周”
nextWeekButton.addEventListener("click", () => {

  if (currentWeek < maxWeek) {

    currentWeek++;

    renderCurrentWeek();

  }

});

/**
 * 页面入口。
 */
async function main() {

  // 1. 先建立空课表
  renderBaseGrid();

  try {

    // 2. 读取 JSON，并保存全部课程
    allCourses = await loadCourses();

    console.log("全部课程：", allCourses);

    // 3. 自动计算最大周数
    maxWeek = Math.max(
      ...allCourses.map(course => course.week)
    );

    console.log("最大周数：", maxWeek);

  
    // 4. 根据今天日期自动计算当前周
    currentWeek = calculateCurrentWeek();

    console.log("当前周：", currentWeek);

    // 5. 显示当前周
    renderCurrentWeek();

  } catch (error) {

    console.error("课程加载失败：", error);

  }
}


main();
