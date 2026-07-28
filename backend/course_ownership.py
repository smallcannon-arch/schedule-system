# -*- coding: utf-8 -*-
"""Resolve courses that CP-SAT must own because of language pull-out rules."""
import re


def _values(value):
    if isinstance(value, (list, tuple, set)):
        source = value
    else:
        source = re.split(r"[、,，;；\s]+", str(value or ""))
    return list(dict.fromkeys(
        str(item or "").strip() for item in source if str(item or "").strip()))


def _arrangement(data, group):
    value = str(
        group.get("arrangement")
        or data.get("nativeArrangement")
        or data.get("native_arrangement")
        or "common"
    ).strip().lower()
    return "distributed" if value == "distributed" else "common"


def native_pull_courses(data):
    """Return (class, subject) pairs that need variables for H18 constraints."""
    requirements = data.get("native_pull_requirements")
    if isinstance(requirements, dict):
        return {
            (str(key[0]).strip(), subject)
            for key, subjects in requirements.items()
            if isinstance(key, (list, tuple)) and key
            for subject in _values(subjects)
            if str(key[0]).strip()
        }

    result = set()
    groups = data.get("nativeGroups") or data.get("native_groups") or []
    for group in groups:
        if _arrangement(data, group) != "distributed":
            continue
        sources = _values(group.get("sources")) or _values(
            group.get("code") or group.get("class"))
        subjects = _values(group.get("pullSubjects") or group.get("pull_subjects"))
        result.update((code, subject) for code in sources for subject in subjects)
    return result
