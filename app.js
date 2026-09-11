/*
  app.js

  当前数据流程：

  courses.json
      ↓ fetch()
  JavaScript 对象
      ↓
  renderBaseGrid()
      ↓
  renderCurrentWeek()
      ↓
  createCourseCard()

  翘课指数流程：

  点击课程
      ↓
  openCourseDetail()
      ↓
  读取 localStorage
      ↓
  没有结果：直接显示问卷
  已有结果：显示结果 + “重新评估”按钮
      ↓
  提交 10 题问卷
      ↓
  计算点名风险 / 缺席后果 / 自学替代性
      ↓
  生成 0~100 翘课指数
      ↓
  保存到 localStorage，并同步回课程小卡片
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
const SKIP_INDEX_STORAGE_KEY = "p4schedule_skip_index";

// =========================================================
// 翘课指数问卷
// score 越高，越有利于“低风险缺席”。
// attendance 最终会换算成“点名风险”，所以展示时会反向。
// =========================================================

const skipQuestions = [
  {
    id: "q1",
    category: "attendance",
    question: "这位老师过去的点名频率怎么样？",
    options: [
      { id: "never", label: "从来没点过", score: 10 },
      { id: "rare", label: "很少点，一个月可能一两次", score: 6 },
      { id: "sometimes", label: "偶尔点", score: 0 },
      { id: "often", label: "经常点", score: -7 },
      { id: "always", label: "基本每节都点", score: -12 }
    ]
  },
  {
    id: "q2",
    category: "attendance",
    question: "老师点名的时间有没有规律？",
    options: [
      { id: "predictable", label: "基本固定、很好预测", score: 3 },
      { id: "fixed_stage", label: "通常只在固定环节考勤", score: 0 },
      { id: "random", label: "时间比较随机", score: -4 },
      { id: "multi_random", label: "可能随机多次确认", score: -7 }
    ]
  },
  {
    id: "q3",
    category: "attendance",
    question: "这门课主要使用什么考勤方式？",
    options: [
      { id: "none", label: "基本没有考勤", score: 8 },
      { id: "normal", label: "普通人工 / 二维码考勤", score: -3 },
      { id: "onsite", label: "需要现场定位等本人完成方式", score: -8 },
      { id: "multi_check", label: "一次课可能有多次现场确认", score: -12 }
    ]
  },
  {
    id: "q4",
    category: "attendance",
    question: "课堂规模怎么样，老师认不认识学生？",
    options: [
      { id: "huge", label: "100 人以上大课，基本不认识个人", score: 4 },
      { id: "large", label: "50～100 人，老师只认识少数学生", score: 2 },
      { id: "normal", label: "普通班级，认识程度一般", score: 0 },
      { id: "small", label: "人数很少，老师基本认识学生", score: -4 }
    ]
  },
  {
    id: "q5",
    category: "consequence",
    question: "出勤、点名和课堂表现占平时成绩的比重大吗？",
    options: [
      { id: "none", label: "基本不计入", score: 8 },
      { id: "low", label: "占比很低", score: 4 },
      { id: "normal", label: "一般", score: 0 },
      { id: "high", label: "占比较明显", score: -6 },
      { id: "very_high", label: "出勤直接影响大量平时分", score: -10 }
    ]
  },
  {
    id: "q6",
    category: "consequence",
    question: "缺席一次通常会有什么后果？",
    options: [
      { id: "none", label: "基本没影响", score: 6 },
      { id: "small", label: "只有很小影响", score: 2 },
      { id: "deduct", label: "会明显扣分", score: -5 },
      { id: "severe", label: "多次缺席会造成严重成绩后果", score: -10 }
    ]
  },
  {
    id: "q7",
    category: "selfStudy",
    question: "期末考试占总成绩的比例怎么样？",
    options: [
      { id: "80plus", label: "80% 以上", score: 6 },
      { id: "60_79", label: "60%～79%", score: 3 },
      { id: "40_59", label: "40%～59%", score: 0 },
      { id: "under40", label: "40% 以下", score: -4 }
    ]
  },
  {
    id: "q8",
    category: "selfStudy",
    question: "老师提供的 PPT / 课程资料完整吗？",
    options: [
      { id: "complete", label: "非常完整，基本覆盖考试内容", score: 5 },
      { id: "good", label: "比较完整", score: 2 },
      { id: "normal", label: "一般", score: 0 },
      { id: "poor", label: "资料很少或者很不完整", score: -4 }
    ]
  },
  {
    id: "q9",
    category: "selfStudy",
    question: "这门课有没有容易获得的替代学习资料？",
    options: [
      { id: "excellent", label: "有完整录播、教材或高质量网络课程", score: 5 },
      { id: "easy", label: "网上资料很好找", score: 2 },
      { id: "normal", label: "主要还是依赖课堂内容", score: 0 },
      { id: "hard", label: "离开课堂后很难找到替代资料", score: -4 }
    ]
  },
  {
    id: "q10",
    category: "selfStudy",
    question: "老师课堂讲的内容和 PPT 有多大差别？",
    options: [
      { id: "ppt_only", label: "基本照 PPT 讲", score: 6 },
      { id: "little_extra", label: "有少量补充", score: 2 },
      { id: "important_extra", label: "有不少 PPT 外的重要内容", score: -4 },
      { id: "mostly_class", label: "大量重点、通知或内容只在课堂讲", score: -7 }
    ]
  }
];

// =========================================================
// DOM
// =========================================================

const scheduleGrid = document.getElementById("scheduleGrid");

const prevWeekButton = document.getElementById("prevWeek");
const nextWeekButton = document.getElementById("nextWeek");
const weekLabel = document.getElementById("weekLabel");

const courseModal = document.getElementById("courseModal");
const closeCourseModalButton = document.getElementById("closeCourseModal");
const courseModalBackdrop = document.querySelector(".course-modal-backdrop");

const detailCourseName = document.getElementById("detailCourseName");
const detailTeacher = document.getElementById("detailTeacher");
const detailLocation = document.getElementById("detailLocation");
const detailTime = document.getElementById("detailTime");
const detailDate = document.getElementById("detailDate");
const detailCourseType = document.getElementById("detailCourseType");

const skipResult = document.getElementById("skipResult");
const skipScore = document.getElementById("skipScore");
const skipLevel = document.getElementById("skipLevel");
const skipEvaluatedTime = document.getElementById("skipEvaluatedTime");

const attendanceRiskLabel = document.getElementById("attendanceRiskLabel");
const attendanceRiskBar = document.getElementById("attendanceRiskBar");
const selfStudyLabel = document.getElementById("selfStudyLabel");
const selfStudyBar = document.getElementById("selfStudyBar");

const skipQuestionnaire = document.getElementById("skipQuestionnaire");
const skipQuestionForm = document.getElementById("skipQuestionForm");
const questionnaireQuestions = document.getElementById("questionnaireQuestions");
const questionnaireMessage = document.getElementById("questionnaireMessage");
const retestSkipIndexButton = document.getElementById("retestSkipIndex");

// =========================================================
// 页面状态
// =========================================================

let allCourses = [];
let currentWeek = 1;
let maxWeek = 1;
let activeCourse = null;
let questionnaireIsOpen = false;

// =========================================================
// 课程数据
// =========================================================

async function loadCourses() {
  const response = await fetch("./courses.json");

  if (!response.ok) {
    throw new Error(`课程数据读取失败：${response.status}`);
  }

  return await response.json();
}

function renderBaseGrid() {
  const corner = document.createElement("div");
  corner.className = "grid-cell corner-cell";
  corner.textContent = "节次";
  scheduleGrid.appendChild(corner);

  DAYS.forEach((day, index) => {
    const header = document.createElement("div");
    header.className = "grid-cell day-header";
    header.textContent = day;
    header.dataset.weekday = index + 1;
    scheduleGrid.appendChild(header);
  });

  const today = new Date().getDay() || 7;
  const todayHeader = scheduleGrid.querySelector(
    `.day-header[data-weekday="${today}"]`
  );
  if (todayHeader) {
    todayHeader.classList.add("today-header");
    todayHeader.innerHTML += "<small>TODAY</small>";
  }

  for (let section = 1; section <= TOTAL_SECTIONS; section++) {
    const sectionLabel = document.createElement("div");
    sectionLabel.className = "grid-cell section-label";
    sectionLabel.textContent = `第 ${section} 节`;
    sectionLabel.style.gridColumn = "1";
    sectionLabel.style.gridRow = `${section + 1}`;
    scheduleGrid.appendChild(sectionLabel);

    for (let weekday = 1; weekday <= 7; weekday++) {
      const cell = document.createElement("div");
      cell.className = "grid-cell";
      cell.dataset.weekday = weekday;
      cell.dataset.section = section;
      scheduleGrid.appendChild(cell);
    }
  }
}

// =========================================================
// localStorage
// =========================================================

function getCourseId(course) {
  return `${course.course}__${course.teacher}`;
}

function getAllSkipResults() {
  const rawData = localStorage.getItem(SKIP_INDEX_STORAGE_KEY);

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

function getSkipResult(course) {
  const results = getAllSkipResults();
  const result = results[getCourseId(course)] || null;

  // 兼容之前“模拟 78 分”的旧数据。
  // 旧版本没有点名风险、自学替代性和问卷答案，
  // 如果直接读取会让新版详情页报错，因此把它当作“尚未正式评估”。
  if (
    !result ||
    typeof result.score !== "number" ||
    !result.attendanceRisk ||
    !result.selfStudy ||
    !result.answers
  ) {
    return null;
  }

  return result;
}

function saveSkipResult(course, result) {
  const results = getAllSkipResults();
  results[getCourseId(course)] = result;

  localStorage.setItem(
    SKIP_INDEX_STORAGE_KEY,
    JSON.stringify(results)
  );
}

// =========================================================
// 翘课指数算法
// =========================================================

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function normalizeCategoryScore(category, answers) {
  const questions = skipQuestions.filter(
    question => question.category === category
  );

  let rawScore = 0;
  let minScore = 0;
  let maxScore = 0;

  questions.forEach(question => {
    const selectedOption = question.options.find(
      option => option.id === answers[question.id]
    );

    if (!selectedOption) {
      return;
    }

    rawScore += selectedOption.score;
    minScore += Math.min(...question.options.map(option => option.score));
    maxScore += Math.max(...question.options.map(option => option.score));
  });

  if (maxScore === minScore) {
    return 50;
  }

  const normalized =
    ((rawScore - minScore) / (maxScore - minScore)) * 100;

  return clamp(Math.round(normalized), 0, 100);
}

function getSkipLevel(score) {
  if (score <= 20) {
    return "风险爆表，别翘";
  }

  if (score <= 40) {
    return "不太适合翘";
  }

  if (score <= 60) {
    return "看情况";
  }

  if (score <= 80) {
    return "比较适合翘";
  }

  return "很适合翘";
}

function getFourLevelLabel(score) {
  if (score <= 24) {
    return "低";
  }

  if (score <= 49) {
    return "较低";
  }

  if (score <= 74) {
    return "较高";
  }

  return "高";
}

function calculateSkipIndex(answers) {
  // attendanceSafety 越高，越不容易因为点名出问题。
  const attendanceSafety = normalizeCategoryScore("attendance", answers);

  // 展示给用户的是“预计点名风险”，因此反向处理。
  const attendanceRisk = 100 - attendanceSafety;

  // 缺席实际后果越轻，consequenceSafety 越高。
  const consequenceSafety = normalizeCategoryScore("consequence", answers);

  // 自学替代性越强，selfStudy 越高。
  const selfStudy = normalizeCategoryScore("selfStudy", answers);

  // 总指数：点名安全 50% + 缺席后果 20% + 自学替代性 30%。
  let totalScore = Math.round(
    attendanceSafety * 0.5 +
    consequenceSafety * 0.2 +
    selfStudy * 0.3
  );

  // 两个极端风险条件设置封顶，避免其他小加分把硬风险完全冲掉。
  if (answers.q3 === "multi_check") {
    totalScore = Math.min(totalScore, 45);
  }

  if (answers.q6 === "severe") {
    totalScore = Math.min(totalScore, 40);
  }

  totalScore = clamp(totalScore, 0, 100);

  return {
    score: totalScore,
    level: getSkipLevel(totalScore),
    attendanceRisk: {
      score: attendanceRisk,
      label: getFourLevelLabel(attendanceRisk)
    },
    selfStudy: {
      score: selfStudy,
      label: getFourLevelLabel(selfStudy)
    },
    consequenceSafety: consequenceSafety,
    answers: answers,
    updatedAt: new Date().toISOString()
  };
}

// =========================================================
// 问卷渲染与提交
// =========================================================

function renderSkipQuestionnaire(savedAnswers = {}) {
  questionnaireQuestions.innerHTML = "";
  questionnaireMessage.textContent = "";

  skipQuestions.forEach((question, questionIndex) => {
    const fieldset = document.createElement("fieldset");
    fieldset.className = "question-card";

    const legend = document.createElement("legend");
    legend.className = "question-title";
    legend.textContent = `${questionIndex + 1}. ${question.question}`;
    fieldset.appendChild(legend);

    const optionsContainer = document.createElement("div");
    optionsContainer.className = "question-options";

    question.options.forEach(option => {
      const label = document.createElement("label");
      label.className = "question-option";

      const input = document.createElement("input");
      input.type = "radio";
      input.name = question.id;
      input.value = option.id;

      if (savedAnswers[question.id] === option.id) {
        input.checked = true;
      }

      const text = document.createElement("span");
      text.textContent = option.label;

      label.appendChild(input);
      label.appendChild(text);
      optionsContainer.appendChild(label);
    });

    fieldset.appendChild(optionsContainer);
    questionnaireQuestions.appendChild(fieldset);
  });
}

function collectQuestionnaireAnswers() {
  const answers = {};

  for (const question of skipQuestions) {
    const selected = skipQuestionForm.querySelector(
      `input[name="${question.id}"]:checked`
    );

    if (!selected) {
      return {
        complete: false,
        missingQuestion: question
      };
    }

    answers[question.id] = selected.value;
  }

  return {
    complete: true,
    answers: answers
  };
}

function openQuestionnaire(savedAnswers = {}) {
  renderSkipQuestionnaire(savedAnswers);
  skipQuestionnaire.classList.remove("hidden");
  questionnaireIsOpen = true;

  if (getSkipResult(activeCourse)) {
    retestSkipIndexButton.textContent = "收起问卷";
  }
}

function closeQuestionnaire() {
  skipQuestionnaire.classList.add("hidden");
  questionnaireIsOpen = false;
  questionnaireMessage.textContent = "";
  retestSkipIndexButton.textContent = "重新评估";
}

// =========================================================
// 结果展示
// =========================================================

function showSkipResult(result) {
  skipResult.classList.remove("hidden");

  skipScore.textContent = result.score;
  skipLevel.textContent = result.level;

  attendanceRiskLabel.textContent = result.attendanceRisk.label;
  attendanceRiskBar.style.width = `${result.attendanceRisk.score}%`;
  attendanceRiskBar.setAttribute(
    "aria-valuenow",
    String(result.attendanceRisk.score)
  );

  selfStudyLabel.textContent = result.selfStudy.label;
  selfStudyBar.style.width = `${result.selfStudy.score}%`;
  selfStudyBar.setAttribute(
    "aria-valuenow",
    String(result.selfStudy.score)
  );

  if (result.updatedAt) {
    const date = new Date(result.updatedAt);
    skipEvaluatedTime.textContent = `上次评估：${date.toLocaleString()}`;
  } else {
    skipEvaluatedTime.textContent = "";
  }
}

function hideSkipResult() {
  skipResult.classList.add("hidden");
}

// =========================================================
// 课程详情弹窗
// =========================================================

function openCourseDetail(course) {
  activeCourse = course;

  detailCourseName.textContent = course.course;
  detailTeacher.textContent = course.teacher;
  detailLocation.textContent = course.location;
  detailDate.textContent = course.date;
  detailCourseType.textContent = course.course_type;

  const startSection = course.periods[0];
  const endSection = course.periods[course.periods.length - 1];

  detailTime.textContent =
    `${course.weekday_name} 第 ${startSection}–${endSection} 节`;

  const result = getSkipResult(course);

  if (result) {
    showSkipResult(result);
    closeQuestionnaire();
    retestSkipIndexButton.classList.remove("hidden");
  } else {
    hideSkipResult();
    retestSkipIndexButton.classList.add("hidden");
    openQuestionnaire();
  }

  courseModal.classList.remove("hidden");
  courseModal.setAttribute("aria-hidden", "false");
  document.body.classList.add("modal-open");

  closeCourseModalButton.focus();
}

function closeCourseDetail() {
  courseModal.classList.add("hidden");
  courseModal.setAttribute("aria-hidden", "true");
  document.body.classList.remove("modal-open");

  activeCourse = null;
  questionnaireIsOpen = false;
  questionnaireMessage.textContent = "";
}

// =========================================================
// 课程卡片
// =========================================================

function getSkipBadgeClass(score) {
  if (score <= 20) {
    return "course-skip-index level-1";
  }

  if (score <= 40) {
    return "course-skip-index level-2";
  }

  if (score <= 60) {
    return "course-skip-index level-3";
  }

  if (score <= 80) {
    return "course-skip-index level-4";
  }

  return "course-skip-index level-5";
}

function createCourseCard(course) {
  const card = document.createElement("article");
  card.className = "course-card";
  card.tabIndex = 0;
  card.setAttribute("role", "button");
  card.setAttribute("aria-label", `查看 ${course.course} 详情`);

  card.style.gridColumn = course.weekday + 1;

  const startSection = course.periods[0];
  const endSection = course.periods[course.periods.length - 1];
  const startRow = startSection + 1;
  const span = endSection - startSection + 1;

  card.style.gridRow = `${startRow} / span ${span}`;

  const courseName = document.createElement("div");
  courseName.className = "course-name";
  courseName.textContent = course.course;
  card.appendChild(courseName);

  const teacher = document.createElement("div");
  teacher.className = "course-meta";
  teacher.textContent = course.teacher;
  card.appendChild(teacher);

  const location = document.createElement("div");
  location.className = "course-meta";
  location.textContent = course.location;
  card.appendChild(location);

  const period = document.createElement("div");
  period.className = "course-meta";
  period.textContent = `第 ${startSection}–${endSection} 节`;
  card.appendChild(period);

  const savedSkipResult = getSkipResult(course);

  if (savedSkipResult) {
    const badge = document.createElement("div");
    badge.className = getSkipBadgeClass(savedSkipResult.score);
    badge.textContent = `翘课指数 ${savedSkipResult.score}`;
    card.appendChild(badge);
  }

  card.addEventListener("click", () => {
    openCourseDetail(course);
  });

  card.addEventListener("keydown", event => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      openCourseDetail(course);
    }
  });

  return card;
}

function renderCourses(courses) {
  courses.forEach(course => {
    scheduleGrid.appendChild(createCourseCard(course));
  });
}

function clearCourseCards() {
  document.querySelectorAll(".course-card").forEach(card => {
    card.remove();
  });
}

function calculateCurrentWeek() {
  // 2026 秋季学期第 1 周周一：2026-09-07
  // JavaScript 月份从 0 开始，因此 8 代表 9 月。
  const semesterStart = new Date(2026, 8, 7);
  const today = new Date();

  semesterStart.setHours(0, 0, 0, 0);
  today.setHours(0, 0, 0, 0);

  const diffTime = today - semesterStart;
  const diffDays = Math.floor(diffTime / (1000 * 60 * 60 * 24));
  const week = Math.floor(diffDays / 7) + 1;

  return clamp(week, 1, maxWeek);
}

function renderCurrentWeek() {
  clearCourseCards();

  const weekCourses = allCourses.filter(
    course => course.week === currentWeek
  );

  weekLabel.textContent = `第 ${currentWeek} 周`;
  renderCourses(weekCourses);

  prevWeekButton.disabled = currentWeek <= 1;
  nextWeekButton.disabled = currentWeek >= maxWeek;
}

// =========================================================
// 事件
// =========================================================

prevWeekButton.addEventListener("click", () => {
  if (currentWeek > 1) {
    currentWeek--;
    renderCurrentWeek();
  }
});

nextWeekButton.addEventListener("click", () => {
  if (currentWeek < maxWeek) {
    currentWeek++;
    renderCurrentWeek();
  }
});

closeCourseModalButton.addEventListener(
  "click",
  closeCourseDetail
);

courseModalBackdrop.addEventListener(
  "click",
  closeCourseDetail
);

document.addEventListener("keydown", event => {
  if (
    event.key === "Escape" &&
    !courseModal.classList.contains("hidden")
  ) {
    closeCourseDetail();
  }
});

retestSkipIndexButton.addEventListener("click", () => {
  if (!activeCourse) {
    return;
  }

  if (questionnaireIsOpen) {
    closeQuestionnaire();
    return;
  }

  const previousResult = getSkipResult(activeCourse);
  openQuestionnaire(previousResult?.answers || {});
});

skipQuestionForm.addEventListener("submit", event => {
  event.preventDefault();

  if (!activeCourse) {
    return;
  }

  const collected = collectQuestionnaireAnswers();

  if (!collected.complete) {
    questionnaireMessage.textContent =
      `请先回答第 ${skipQuestions.indexOf(collected.missingQuestion) + 1} 题。`;

    const missingCard = skipQuestionForm
      .querySelector(`input[name="${collected.missingQuestion.id}"]`)
      ?.closest(".question-card");

    missingCard?.scrollIntoView({
      behavior: "smooth",
      block: "center"
    });

    return;
  }

  const result = calculateSkipIndex(collected.answers);

  saveSkipResult(activeCourse, result);
  showSkipResult(result);
  closeQuestionnaire();
  retestSkipIndexButton.classList.remove("hidden");

  // 重新渲染当前周，让课程小卡片立刻显示最新指数。
  renderCurrentWeek();
});


function updateTodayCard() {
  const dayNames = ["周日","周一","周二","周三","周四","周五","周六"];
  const today = new Date().getDay();
  const todayWeekday = today === 0 ? 7 : today;

  const dayEl = document.getElementById("todayDay");
  const courseEl = document.getElementById("todayCourse");
  const infoEl = document.getElementById("todayInfo");

  if (!dayEl || !courseEl || !infoEl || !allCourses.length) return;

  dayEl.textContent = dayNames[today];

  const todayCourses = allCourses.filter(
    c => c.week === currentWeek && c.weekday === todayWeekday
  );

  if (todayCourses.length === 0) {
    courseEl.textContent = "暂无课程";
    infoEl.textContent = "今天没有安排课程";
    return;
  }

  const c = todayCourses[0];
  courseEl.textContent = c.course;
  infoEl.textContent =
    `${c.location} · 第 ${c.periods[0]}-${c.periods[c.periods.length-1]} 节`;
}

// =========================================================
// 页面入口
// =========================================================

async function main() {
  renderBaseGrid();

  try {
    allCourses = await loadCourses();

    maxWeek = Math.max(
      ...allCourses.map(course => course.week)
    );

    currentWeek = calculateCurrentWeek();
    renderCurrentWeek();
    updateTodayCard();
  } catch (error) {
    console.error("课程加载失败：", error);

    const message = document.createElement("div");
    message.className = "message";
    message.textContent = "课程加载失败，请检查 courses.json 是否存在。";
    scheduleGrid.appendChild(message);
  }
}

main();
