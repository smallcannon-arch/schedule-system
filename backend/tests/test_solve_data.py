from fastapi.testclient import TestClient

import app


CLIENT = TestClient(app.app)


def test_default_mode_uses_cp_sat_and_leaves_tutor_lessons_manual():
    request = app.SolveDataRequest(data={})

    assert request.auto_schedule_tutor is False
    assert request.strict_complete is False
    assert request.diagnostic_draft is False
    assert "CP-SAT 排課引擎" in app.PAGE
    assert "不需要 AI 或模型 API" in app.PAGE
    assert 'name="use_openai"' not in app.PAGE


def test_solve_data_returns_json_schedule_and_workbook(monkeypatch):
    meta = {
        "status": "OPTIMAL", "penalty": 0, "best_bound": 0, "relative_gap": 0,
        "wall": 0.1, "conflicts": 0, "branches": 0, "required_total": 1,
        "scheduled_total": 1, "remaining_total": 0, "pool_total": 0,
        "missing_total": 0, "completion": "complete", "weekly_cap_violations": [],
        "missing_courses": [], "incomplete_totals": {},
        "quality_report": [{
            "rule_id": "S01", "label": "國語文優先排上午", "enabled": True,
            "weight": 4, "violations": 0, "weighted_penalty": 0,
            "details": [], "details_truncated": False,
        }],
        "quality_violation_total": 0, "quality_penalty_total": 0,
        "auto_schedule_tutor": True,
    }
    monkeypatch.setattr(app, "_check_solve_access", lambda *args: True)
    monkeypatch.setattr(app, "_claim_rate_limit", lambda: True)
    monkeypatch.setattr(app, "_run_solver_data", lambda *args: (
        b"workbook", meta, "disabled",
        [{"code": "1甲", "day": "一", "period": 1, "subject": "國語文",
          "teacher": "王老師", "room": "R00"}], [],
    ))

    response = CLIENT.post("/solve-data", json={
        "data": {"classes": [{"code": "1甲"}], "subjects": {"國語文": {}}},
        "limits": [], "rules": [], "strict_complete": True,
    })

    assert response.status_code == 200
    assert response.json()["schedule"][0]["teacher"] == "王老師"
    assert response.json()["workbook_base64"] == "d29ya2Jvb2s="
    assert response.json()["meta"]["quality_report"][0]["rule_id"] == "S01"
    assert response.json()["meta"]["missing_courses"] == []
    assert response.headers["X-Schedule-Completeness"] == "complete"


def test_loaded_solver_maps_resource_group_and_pull_subject(monkeypatch):
    overlay = [("group-a-1", "一年級A組", "1甲", "國語文", "綜合活動",
                "資源教師", "一", 1)]
    monkeypatch.setattr(app.engine, "solve", lambda *args, **kwargs: (
        {}, {}, [], {"status": "OPTIMAL"}, overlay))
    monkeypatch.setattr(app.engine, "validate", lambda *args, **kwargs: [])

    def write_output(path, *args, **kwargs):
        with open(path, "wb") as stream:
            stream.write(b"workbook")

    monkeypatch.setattr(app.engine, "write_output", write_output)

    output, _, _, _, overlay_rows = app._solve_loaded_data({}, 5)

    assert output == b"workbook"
    assert overlay_rows == [{
        "group_id": "group-a-1", "group": "一年級A組", "code": "1甲",
        "subject": "國語文", "pull_subject": "綜合活動", "teacher": "資源教師",
        "day": "一", "period": 1,
    }]


def test_solve_data_marks_diagnostic_draft_and_uses_draft_filename(monkeypatch):
    captured = {}
    meta = {
        "status": "FEASIBLE", "penalty": 0, "best_bound": 0, "relative_gap": 0,
        "wall": 0.1, "conflicts": 0, "branches": 0, "required_total": 2,
        "scheduled_total": 1, "remaining_total": 1, "pool_total": 0,
        "missing_total": 0, "diagnostic_shortfall_total": 1,
        "completion": "partial", "weekly_cap_violations": [],
        "missing_courses": [{
            "class": "1甲", "subject": "國語文", "hours": 1,
            "required": 2, "scheduled": 1,
            "reason_code": "diagnostic_shortfall", "reason": "診斷草案未排入",
        }],
        "incomplete_totals": {"diagnostic_shortfall": 1},
        "quality_report": [], "quality_violation_total": 0,
        "quality_penalty_total": 0, "diagnostic_draft": True,
        "diagnostic_quality_optimized": True,
    }

    def fake_solver(*args):
        captured["diagnostic_draft"] = args[-1]
        return b"draft", meta, "disabled", [{
            "code": "1甲", "day": "一", "period": 1, "subject": "國語文",
            "teacher": "王老師", "room": "R00",
        }], []

    monkeypatch.setattr(app, "_check_solve_access", lambda *args: True)
    monkeypatch.setattr(app, "_claim_rate_limit", lambda: True)
    monkeypatch.setattr(app, "_run_solver_data", fake_solver)

    response = CLIENT.post("/solve-data", json={
        "data": {"classes": [{"code": "1甲"}], "subjects": {"國語文": {}}},
        "diagnostic_draft": True,
    })

    assert response.status_code == 200
    assert captured["diagnostic_draft"] is True
    assert response.json()["filename"] == "schedule_diagnostic_draft.xlsx"
    assert response.json()["meta"]["diagnostic_draft"] is True
    assert response.headers["X-Diagnostic-Draft"] == "true"


def test_solve_data_returns_structured_cp_sat_diagnostics(monkeypatch):
    monkeypatch.setattr(app, "_check_solve_access", lambda *args: True)
    monkeypatch.setattr(app, "_claim_rate_limit", lambda: True)

    def fail(*args):
        raise app.engine.InfeasibleScheduleError(
            "無可行解，硬規則彼此衝突",
            [{"title": "王老師的授課容量不足", "detail": "需要 22 節，最多可排 20 節。",
              "action": "調整配課或不排課時間。", "view": "alloc", "confirmed": True}])

    monkeypatch.setattr(app, "_run_solver_data", fail)
    response = CLIENT.post("/solve-data", json={"data": {}, "limits": [], "rules": []})

    assert response.status_code == 422
    payload = response.json()
    assert payload["status"] == "INFEASIBLE"
    assert payload["diagnostic_engine"] == "cp-sat-rules"
    assert payload["diagnostics"][0]["view"] == "alloc"
    assert payload["diagnostics"][0]["confirmed"] is True
