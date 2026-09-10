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
// 保存全部课程
let allCourses = [];

// 当前显示第几周
let currentWeek = 1;

// 最大周数，后面从 JSON 自动计算
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

  card.innerHTML = `
    <div class="course-name">${course.course}</div>

    <div class="course-meta">
      ${course.teacher}
    </div>

    <div class="course-meta">
      ${course.location}
    </div>

    <div class="course-meta">
      第 ${startSection}–${endSection} 节
    </div>
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

    // 4. 默认显示第 1 周
    renderCurrentWeek();

  } catch (error) {

    console.error("课程加载失败：", error);

  }
}


main();
