# -*- coding: utf-8 -*-
"""Resolve course rooms consistently across solve, publish, and teacher views."""


def normalized_course_room(data, code, subject, teacher=""):
    """Resolve a room from normalized engine data."""
    assigned = str(teacher or (data.get("assign") or {}).get((code, subject), "") or "").strip()
    return (
        (data.get("room_override") or {}).get((code, subject))
        or (data.get("teacher_room_override") or {}).get((assigned, subject))
        or ((data.get("subjects") or {}).get(subject) or {}).get("room")
        or "R00"
    )


def frontend_course_room(data, code, subject, teacher=""):
    """Resolve a room from the browser snapshot shape."""
    assigned = str(
        teacher
        or ((data.get("assign") or {}).get(str(code)) or {}).get(subject)
        or ""
    ).strip()
    class_override = (data.get("override") or {}).get(str(code)) or {}
    teacher_override = (data.get("teacherRooms") or {}).get(subject) or {}
    return (
        class_override.get(subject)
        or teacher_override.get(assigned)
        or ((data.get("subjects") or {}).get(subject) or {}).get("room")
        or "R00"
    )
