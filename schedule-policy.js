(function (root) {
  "use strict";

  const PROFILE_ID = "tw-elementary-custom-v1";
  const LEGACY_PROFILE_ID = "hsinchu-elementary-115";
  const PROFILE = Object.freeze({
    id: PROFILE_ID,
    label: "國民小學自訂規則",
    region: "",
    academicYear: 0,
    schoolType: "國民小學",
    periodMinutes: 40,
    dailyPeriods: 7,
    dailyHardCap: 6,
    gradeTotals: {
      1: [22, 24], 2: [22, 24], 3: [28, 31],
      4: [28, 31], 5: [30, 33], 6: [30, 33],
    },
    fixedWeeklyTargets: {"專任輔導教師": 0, "教支人員": 0, "鐘點教師": 0, "其他": 0, "": 0},
    softDailyTargets: {"導師": 4, "科任": 5, "資源班教師": 5},
  });

  const LEGACY_DIRECTOR_TARGETS = [[12, 4], [24, 3], [30, 3], [36, 2], [48, 1], [60, 1], [Infinity, 0]];
  const LEGACY_CHIEF_TARGETS = [[12, 10], [24, 9], [30, 8], [36, 8], [48, 7], [60, 7], [Infinity, 6]];

  function normalize(data) {
    const source = data.policy && typeof data.policy === "object" ? data.policy : {};
    const targets = source.weeklyTargets && typeof source.weeklyTargets === "object" ? source.weeklyTargets : {};
    const legacy = source.profileId === LEGACY_PROFILE_ID;
    const officialCount = Math.max(0, Number(source.officialClassCount) || 0);
    const classCount = officialCount || (data.classes || []).length;
    data.policy = {
      profileId: PROFILE_ID,
      region: String(source.region || (legacy ? "新竹市" : "")).trim().slice(0, 30),
      academicYear: integerBetween(source.academicYear, legacy ? 115 : 0, 0, 999),
      periodMinutes: integerBetween(source.periodMinutes, 40, 1, 120),
      dailyHardCap: integerBetween(source.dailyHardCap, 6, 1, 6),
      officialClassCount: officialCount,
      weeklyTargets: {
        "導師": numberOrNull(targets["導師"], legacy ? 16 : 0),
        "科任": numberOrNull(targets["科任"], legacy ? 20 : 0),
        "組長": numberOrNull(targets["組長"], legacy ? tierValue(LEGACY_CHIEF_TARGETS, classCount) : 0),
        "主任": numberOrNull(targets["主任"], legacy ? tierValue(LEGACY_DIRECTOR_TARGETS, classCount) : 0),
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

  function integerBetween(value, fallback, minimum, maximum) {
    const parsed = Number(value);
    if (!Number.isFinite(parsed)) return fallback;
    return Math.min(maximum, Math.max(minimum, Math.round(parsed)));
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
    const sharedRole = {"資源班教師": "科任", "資源班導師": "導師",
      "導師兼主任": "導師", "導師兼組長": "導師"}[role];
    if (sharedRole) return weeklyTarget(data, sharedRole);
    if (["導師", "科任", "組長", "主任"].includes(role)) {
      return config.weeklyTargets[role];
    }
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
    for (const [teacher, custom] of Object.entries(data.tcap)) {
      if (!custom || typeof custom !== "object" || custom.extra !== undefined) continue;
      let role = (data.roster || {})[teacher] || "";
      role = {"資源班教師": "科任", "資源班導師": "導師",
        "導師兼主任": "導師", "導師兼組長": "導師"}[role] || role;
      const base = ["導師", "科任", "組長", "主任"].includes(role) ?
        Number(data.policy.weeklyTargets[role]) || 0 : PROFILE.fixedWeeklyTargets[role] || 0;
      const oldTarget = Math.max(0, Number(custom.cap) || base);
      const oldMinus = Math.max(0, Number(custom.minus) || 0);
      const netBeforeMinus = oldTarget;
      custom.extra = Math.max(0, netBeforeMinus - base);
      custom.minus = oldMinus + Math.max(0, base - netBeforeMinus);
      delete custom.cap;
    }
  }

  function hardDailyCap(data) {
    return data ? normalize(data).dailyHardCap : PROFILE.dailyHardCap;
  }

  function validate(data, options) {
    const config = normalize(data);
    const blocking = [];
    const warnings = [];
    const actualClasses = (data.classes || []).length;
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

    for (const [teacher, value] of Object.entries(data.tcap || {})) {
      const minus = Math.max(0, Number(value.minus) || 0);
      const reason = String(value.reason || "");
      if (!minus) continue;
      if (!reason) warnings.push(`${teacher}已設定減課 ${minus} 節，但尚未填寫減課原因`);
    }

    if (!config.region) warnings.push("尚未填寫縣市或適用規則名稱");
    if (!config.academicYear) warnings.push("尚未填寫適用學年度");
    if (!Object.values(config.weeklyTargets).some(Boolean)) {
      warnings.push("尚未填寫教師每週基準節數；填 0 的職務將不檢核應授節數");
    }

    if (options && options.requireApproval) {
      if (!config.region || !config.academicYear) {
        blocking.push("正式發布前須填寫縣市或適用規則名稱及學年度");
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
    hardDailyCap,
    validate,
  };
}(typeof globalThis !== "undefined" ? globalThis : window));
