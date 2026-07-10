(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.ScheduleEditor = api;
}(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  function clone(value) {
    return JSON.parse(JSON.stringify(value));
  }

  function isResourceBound(data, code, subject) {
    const classroom = (data.classes || []).find((item) => item.code === code);
    const classWide = Boolean(classroom && classroom.res &&
      (subject === "國語文" || subject === "數學"));
    return classWide || (data.resGroups || []).some((group) =>
      group.code === code && group.subj === subject);
  }

  function lockedReason(data, schedule, overlays, code, day, period) {
    const key = `${code}|${day}|${period}`;
    const entry = (schedule || {})[key];
    if ((overlays || []).some((item) =>
      item.code === code && item.d === day && Number(item.p) === Number(period))) {
      return "資源班抽離綁課";
    }
    if (entry && isResourceBound(data, code, entry.s)) return "資源班綁課";
    if ((data.locks || []).some((item) =>
      item.c === code && item.d === day && Number(item.p) === Number(period))) {
      return "固定課鎖定";
    }
    const block = entry && data.subjects && data.subjects[entry.s] &&
      String(data.subjects[entry.s].block || "");
    if (block) return `${block} 課程需整組調整`;
    return "";
  }

  function flatten(snapshot) {
    const result = {};
    for (const [key, value] of Object.entries((snapshot && snapshot.sol) || {})) {
      result[`engine|${key}`] = {
        subject: value.s || "", teacher: value.t || "", room: value.room || "",
      };
    }
    for (const [code, placements] of Object.entries((snapshot && snapshot.tp) || {})) {
      for (const [slot, subject] of Object.entries(placements || {})) {
        result[`tutor|${code}|${slot}`] = {subject, teacher: "", room: ""};
      }
    }
    return result;
  }

  function diffSnapshots(before, after) {
    const left = flatten(before);
    const right = flatten(after);
    const keys = [...new Set([...Object.keys(left), ...Object.keys(right)])].sort();
    const changes = [];
    for (const key of keys) {
      const previous = left[key] || null;
      const current = right[key] || null;
      if (JSON.stringify(previous) === JSON.stringify(current)) continue;
      changes.push({
        key,
        kind: previous && current ? "changed" : (previous ? "removed" : "added"),
        before: previous,
        after: current,
      });
    }
    return changes;
  }

  return {clone, isResourceBound, lockedReason, flatten, diffSnapshots};
}));
