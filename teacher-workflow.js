(function (root, factory) {
  const api = factory(root);
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.TeacherWorkflow = api;
}(typeof globalThis !== "undefined" ? globalThis : this, function (root) {
  "use strict";

  function clone(value) {
    return JSON.parse(JSON.stringify(value));
  }

  function webCrypto() {
    if (!root.crypto || !root.crypto.subtle) throw new Error("此瀏覽器不支援安全加密");
    return root.crypto;
  }

  function bytesToBase64(value) {
    const bytes = value instanceof Uint8Array ? value : new Uint8Array(value);
    let binary = "";
    for (let index = 0; index < bytes.length; index += 1) {
      binary += String.fromCharCode(bytes[index]);
    }
    return root.btoa(binary);
  }

  function base64ToBytes(value) {
    const binary = root.atob(String(value || ""));
    const bytes = new Uint8Array(binary.length);
    for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
    return bytes;
  }

  async function deriveAccessKey(accessCode, salt, iterations, usage) {
    if (String(accessCode || "").length < 8) throw new Error("班級調整碼至少需要 8 個字元");
    const cryptoApi = webCrypto();
    const encoder = new TextEncoder();
    const keyMaterial = await cryptoApi.subtle.importKey(
      "raw", encoder.encode(accessCode), "PBKDF2", false, ["deriveKey"]);
    return cryptoApi.subtle.deriveKey(
      {name: "PBKDF2", salt, iterations, hash: "SHA-256"},
      keyMaterial,
      {name: "AES-GCM", length: 256},
      false,
      [usage],
    );
  }

  async function encryptPackage(payload, accessCode) {
    const cryptoApi = webCrypto();
    const salt = cryptoApi.getRandomValues(new Uint8Array(16));
    const iv = cryptoApi.getRandomValues(new Uint8Array(12));
    const iterations = 210000;
    const key = await deriveAccessKey(accessCode, salt, iterations, "encrypt");
    const encoder = new TextEncoder();
    const additionalData = encoder.encode("schedule-teacher-encrypted-v1");
    const ciphertext = await cryptoApi.subtle.encrypt(
      {name: "AES-GCM", iv, additionalData},
      key,
      encoder.encode(JSON.stringify(payload)),
    );
    return {
      schema: "schedule-teacher-encrypted-v1",
      kdf: "PBKDF2-SHA256",
      cipher: "AES-256-GCM",
      iterations,
      salt: bytesToBase64(salt),
      iv: bytesToBase64(iv),
      ciphertext: bytesToBase64(ciphertext),
    };
  }

  async function decryptPackage(envelope, accessCode) {
    if (!envelope || envelope.schema !== "schedule-teacher-encrypted-v1") {
      throw new Error("檔案不是加密的教師調整檔");
    }
    const iterations = Number(envelope.iterations);
    if (!Number.isInteger(iterations) || iterations < 100000 || iterations > 500000) {
      throw new Error("調整檔的加密參數無效");
    }
    const salt = base64ToBytes(envelope.salt);
    const iv = base64ToBytes(envelope.iv);
    if (salt.length !== 16 || iv.length !== 12) throw new Error("調整檔的加密資料無效");
    const key = await deriveAccessKey(accessCode, salt, iterations, "decrypt");
    const additionalData = new TextEncoder().encode("schedule-teacher-encrypted-v1");
    try {
      const plaintext = await webCrypto().subtle.decrypt(
        {name: "AES-GCM", iv, additionalData}, key, base64ToBytes(envelope.ciphertext));
      return JSON.parse(new TextDecoder().decode(plaintext));
    } catch (error) {
      throw new Error("班級調整碼錯誤，或調整檔已損毀");
    }
  }

  function randomAccessCode(length = 12) {
    const alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789";
    const bytes = webCrypto().getRandomValues(new Uint8Array(Math.max(8, length)));
    return [...bytes].map((value) => alphabet[value % alphabet.length]).join("");
  }

  function isResourceBound(data, code, subject) {
    const classroom = (data.classes || []).find((item) => item.code === code);
    const classWide = Boolean(classroom && classroom.res &&
      (subject === "國語文" || subject === "數學"));
    const groupBound = (data.resGroups || []).some((group) =>
      group.code === code && group.subj === subject);
    return classWide || groupBound;
  }

  function isResourceLockedSlot(data, schedule, overlays, code, day, period) {
    const key = `${code}|${day}|${period}`;
    const entry = schedule && schedule[key];
    if (entry && isResourceBound(data, code, entry.s)) return true;
    return (overlays || []).some((item) =>
      item.code === code && item.d === day && Number(item.p) === Number(period));
  }

  function fixedSignature(data, schedule, overlays, code, teacherBusy) {
    const classroom = (data.classes || []).find((item) => item.code === code) || {};
    const fixed = Object.entries(schedule || {})
      .filter(([key]) => key.split("|")[0] === code)
      .map(([key, value]) => [key, value.s || "", value.t || "", value.room || ""])
      .sort((a, b) => a[0].localeCompare(b[0]));
    const overlay = (overlays || [])
      .filter((item) => item.code === code)
      .map((item) => [item.grp || "", item.subj || "", item.t || "", item.d || "", Number(item.p) || 0])
      .sort((a, b) => JSON.stringify(a).localeCompare(JSON.stringify(b)));
    const relevantLimits = (data.limits || [])
      .filter((row) => row[0] === classroom.tutor || row[0] === code || row[0] === `${classroom.g}年級`)
      .map((row) => clone(row))
      .sort((a, b) => JSON.stringify(a).localeCompare(JSON.stringify(b)));
    const boundSubjects = Object.keys(data.subjects || {})
      .filter((subject) => isResourceBound(data, code, subject)).sort();
    return JSON.stringify({
      code,
      tutor: classroom.tutor || "",
      fixed,
      overlay,
      boundSubjects,
      locks: (data.locks || []).filter((item) => item.c === code)
        .map((item) => clone(item)).sort((a, b) => JSON.stringify(a).localeCompare(JSON.stringify(b))),
      limits: relevantLimits,
      gradeSlots: clone((data.gslot || {})[classroom.g] || []),
      teacherBusy: [...(teacherBusy || [])].sort(),
    });
  }

  return {clone, encryptPackage, decryptPackage, randomAccessCode,
    isResourceBound, isResourceLockedSlot, fixedSignature};
}));
