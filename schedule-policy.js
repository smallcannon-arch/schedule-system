(function (root) {
  "use strict";

  const PROFILE_ID = "hsinchu-elementary-115";
  const PROFILE = Object.freeze({
    id: PROFILE_ID,
    label: "新竹市國民小學 115 學年度",
    region: "新竹市",
    academicYear: 115,
    schoolType: "國民小學",
    effectiveFrom: "2026-08-01",
    periodMinutes: 40,
    dailyPeriods: 7,
    dailyHardCap: 6,
    gradeTotals: {
      1: [22, 24], 2: [22, 24], 3: [28, 31],
      4: [28, 31], 5: [30, 33], 6: [30, 33],
    },
    fixedWeeklyTargets: {
      "導師": 16,
      "科任": 20,
      "專任輔導教師": 0,
      "教支人員": 0,
      "鐘點教師": 0,
      "其他": 0,
      "": 0,
    },
    directorTargets: [[12, 4], [24, 3], [30, 3], [36, 2], [48, 1], [60, 1], [Infinity, 0]],
    chiefTargets: [[12, 10], [24, 9], [30, 8], [36, 8], [48, 7], [60, 7], [Infinity, 6]],
    adminReductionTotals: [[18, 10], [48, 12], [Infinity, 14]],
    softDailyTargets: {"導師": 4, "科任": 5, "資源班教師": 5},
    sources: [
      {
        title: "新竹市國民小學教師每週授課節數規定（自115學年度起實施）",
        effectiveFrom: "2026-08-01",
        url: "https://www.hc.edu.tw/edub/rule/rule.aspx",
      },
      {
        title: "新竹市高級中等以下學校學生在校作息時間注意事項",
        effectiveFrom: "2026-03-12",
        url: "https://law.hccg.gov.tw/LawContent.aspx?id=GL000113",
      },
    ],
  });

  function normalize(data) {
    const source = data.policy && typeof data.policy === "object" ? data.policy : {};
    const targets = source.weeklyTargets && typeof source.weeklyTargets === "object" ? source.weeklyTargets : {};
    data.policy = {
      profileId: PROFILE_ID,
      officialClassCount: Math.max(0, Number(source.officialClassCount) || 0),
      weeklyTargets: {
        "導師": numberOrNull(targets["導師"], 16),
        "科任": numberOrNull(targets["科任"], 20),
        "組長": numberOrNull(targets["組長"], null),
        "主任": numberOrNull(targets["主任"], null),
      },
      staffingPrinciplesApproved: source.staffingPrinciplesApproved === true,
      staffingMeetingDate: String(source.staffingMeetingDate || ""),
      schedulePlanApproved: source.schedulePlanApproved === true,
      schedulePlanMeetingDate: String(source.schedulePlanMeetingDate || ""),
    };
    migrateTeacherAdjustments(data);
    return data.policy;
  }

  function numberOrNull(value, fallback) {
    if (value === null || value === undefined || value === "") return fallback;
    const parsed = Number(value);
    return Number.isFinite(parsed) ? Math.max(0, parsed) : fallback;
  }

  function officialClassCount(data) {
    const config = normalize(data);
    return config.officialClassCount || (data.classes || []).length;
  }

  function tierValue(rows, count) {
    return rows.find(([maximum]) => count <= maximum)?.[1] || 0;
  }

  function weeklyTarget(data, role) {
    const config = normalize(data);
    const count = officialClassCount(data);
    const sharedRole = {"資源班教師": "科任", "資源班導師": "導師",
      "導師兼主任": "導師", "導師兼組長": "導師"}[role];
    if (sharedRole) return weeklyTarget(data, sharedRole);
    if (["導師", "科任", "組長", "主任"].includes(role)) {
      const configured = config.weeklyTargets[role];
      if (configured !== null) return configured;
    }
    if (role === "主任") return tierValue(PROFILE.directorTargets, count);
    if (role === "組長") return tierValue(PROFILE.chiefTargets, count);
    return PROFILE.fixedWeeklyTargets[role] || 0;
  }

  function teacherTarget(data, teacher) {
    normalize(data);
    const custom = (data.tcap || {})[teacher] || {};
    const base = weeklyTarget(data, (data.roster || {})[teacher] || "");
    return Math.max(0, base + (Number(custom.extra) || 0) - (Number(custom.minus) || 0));
  }

  function hasWeeklyTarget(role) {
    return ["導師", "科任", "組長", "主任", "導師兼組長", "導師兼主任",
      "資源班教師", "資源班導師", "專任輔導教師"].includes(role);
  }

  function migrateTeacherAdjustments(data) {
    data.tcap = data.tcap || {};
    const count = (data.policy && data.policy.officialClassCount) || (data.classes || []).length;
    for (const [teacher, custom] of Object.entries(data.tcap)) {
      if (!custom || typeof custom !== "object" || custom.extra !== undefined) continue;
      let role = (data.roster || {})[teacher] || "";
      role = {"資源班教師": "科任", "資源班導師": "導師",
        "導師兼主任": "導師", "導師兼組長": "導師"}[role] || role;
      let base = PROFILE.fixedWeeklyTargets[role] || 0;
      if (role === "主任") base = tierValue(PROFILE.directorTargets, count);
      if (role === "組長") base = tierValue(PROFILE.chiefTargets, count);
      const oldTarget = Math.max(0, Number(custom.cap) || base);
      const oldMinus = Math.max(0, Number(custom.minus) || 0);
      const netBeforeMinus = oldTarget;
      custom.extra = Math.max(0, netBeforeMinus - base);
      custom.minus = oldMinus + Math.max(0, base - netBeforeMinus);
      delete custom.cap;
    }
  }

  function setSuggestedWeeklyTargets(data) {
    const config = normalize(data);
    const count = officialClassCount(data);
    config.weeklyTargets = {
      "導師": 16,
      "科任": 20,
      "組長": tierValue(PROFILE.chiefTargets, count),
      "主任": tierValue(PROFILE.directorTargets, count),
    };
    return config.weeklyTargets;
  }

  function hardDailyCap() {
    return PROFILE.dailyHardCap;
  }

  function adminReductionLimit(data) {
    return tierValue(PROFILE.adminReductionTotals, officialClassCount(data));
  }

  function validate(data, options) {
    const config = normalize(data);
    const blocking = [];
    const warnings = [];
    const actualClasses = (data.classes || []).length;
    const count = officialClassCount(data);
    if (config.officialClassCount && config.officialClassCount < actualClasses) {
      blocking.push(`校務核定班級數 ${config.officialClassCount} 不可少於已建立班級 ${actualClasses} 班`);
    }

    const grades = new Set((data.classes || []).map((item) => Number(item.g)).filter(Boolean));
    for (const grade of grades) {
      const total = Object.values(data.subjects || {}).reduce((sum, subject) =>
        sum + Math.max(0, Number((subject.hours || [])[grade - 1]) || 0), 0);
      const [minimum, maximum] = PROFILE.gradeTotals[grade] || [0, Infinity];
      if (total < minimum || total > maximum) {
        blocking.push(`${grade}年級每週學習總節數 ${total} 節，應介於 ${minimum} 至 ${maximum} 節`);
      }
    }

    let adminReduction = 0;
    for (const [teacher, value] of Object.entries(data.tcap || {})) {
      const minus = Math.max(0, Number(value.minus) || 0);
      const reason = String(value.reason || "");
      if (!minus) continue;
      if (!reason) warnings.push(`${teacher}已設定減課 ${minus} 節，但尚未填寫減課原因`);
      if (reason === "英語種子教師" && minus !== 1) blocking.push(`${teacher}的英語種子教師減課應為 1 節`);
      if (reason === "兼任輔導教師" && minus !== 2) blocking.push(`${teacher}的兼任輔導教師減課應為 2 節`);
      if (reason === "導師兼行政職務" && minus !== 4) blocking.push(`${teacher}的導師兼行政職務減課應為 4 節`);
      if (reason === "協助行政工作") {
        adminReduction += minus;
        if (minus < 1 || minus > 4) blocking.push(`${teacher}協助行政工作減課應介於 1 至 4 節`);
      }
    }
    const adminLimit = adminReductionLimit(data);
    if (adminReduction > adminLimit) {
      blocking.push(`協助行政工作減課合計 ${adminReduction} 節，超過 ${count} 班學校上限 ${adminLimit} 節`);
    }

    if (!config.staffingPrinciplesApproved) warnings.push("授課節數編配原則尚未確認經校務會議審議通過");
    else if (!config.staffingMeetingDate) warnings.push("尚未填寫授課節數編配原則的校務會議日期");
    if (!config.schedulePlanApproved) warnings.push("學生作息與課表尚未確認納入課程計畫");
    else if (!config.schedulePlanMeetingDate) warnings.push("尚未填寫課程計畫通過日期");

    if (options && options.requireApproval) {
      if (!config.staffingPrinciplesApproved || !config.staffingMeetingDate) {
        blocking.push("正式發布前須確認授課節數編配原則已經校務會議審議通過並填寫日期");
      }
      if (!config.schedulePlanApproved || !config.schedulePlanMeetingDate) {
        blocking.push("正式發布前須確認學生作息與課表已納入課程計畫並填寫通過日期");
      }
    }
    return {blocking: [...new Set(blocking)], warnings: [...new Set(warnings)]};
  }

  root.SchedulePolicy = {
    profile: PROFILE,
    normalize,
    officialClassCount,
    weeklyTarget,
    teacherTarget,
    hasWeeklyTarget,
    setSuggestedWeeklyTargets,
    hardDailyCap,
    adminReductionLimit,
    validate,
  };
}(typeof globalThis !== "undefined" ? globalThis : window));
