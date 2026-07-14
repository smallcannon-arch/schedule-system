from fastapi.testclient import TestClient

import app


CLIENT = TestClient(app.app)


def test_default_mode_uses_cp_sat_and_leaves_tutor_lessons_manual():
    request = app.SolveDataRequest(data={})

    assert request.auto_schedule_tutor is False
    assert request.strict_complete is False
    assert "CP-SAT 排課引擎" in app.PAGE
    assert "不需要 AI 或模型 API" in app.PAGE
    assert 'name="use_openai"' not in app.PAGE


def test_solve_data_returns_json_schedule_and_workbook(monkeypatch):
    meta = {
        "status": "OPTIMAL", "penalty": 0, "best_bound": 0, "relative_gap": 0,
        "wall": 0.1, "conflicts": 0, "branches": 0, "required_total": 1,
        "scheduled_total": 1, "remaining_total": 0, "pool_total": 0,
        "missing_total": 0, "completion": "complete", "weekly_cap_violations": [],
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
    assert response.headers["X-Schedule-Completeness"] == "complete"


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
