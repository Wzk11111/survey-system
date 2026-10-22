# 接口测试，把作业要求的那些功能挨个过一遍
import datetime

from tests.helpers import register_login, login


def create_survey(client, title="测试问卷", anon=False):
    r = client.post("/api/surveys", json={"title": title, "description": "说明", "allow_anonymous": anon})
    assert r.status_code == 200
    return r.get_json()["sid"]


def add_question(client, sid, payload):
    r = client.post(f"/api/surveys/{sid}/questions", json=payload)
    assert r.status_code == 200, r.get_json()
    return r.get_json()["qid"]


def test_register_login_logout_me(client):
    r = client.post("/api/register", json={"username": "alice", "password": "abc12345"})
    assert r.status_code == 200
    assert client.post("/api/register",
                       json={"username": "alice", "password": "abc12345"}).status_code == 409
    assert client.post("/api/login",
                       json={"username": "alice", "password": "wrong"}).status_code == 401
    assert client.post("/api/login",
                       json={"username": "alice", "password": "abc12345"}).status_code == 200
    assert client.get("/api/me").get_json()["username"] == "alice"
    assert client.post("/api/logout").status_code == 200
    assert client.get("/api/me").status_code == 401


def test_create_and_list_survey(client):
    register_login(client, "bob")
    sid = create_survey(client, "满意度调查")
    items = client.get("/api/surveys").get_json()["surveys"]
    assert len(items) == 1
    assert items[0]["sid"] == sid
    assert items[0]["status"] == "draft"
    assert items[0]["question_count"] == 0

    r = client.put(f"/api/surveys/{sid}",
                   json={"title": "新标题", "deadline": "2026-12-31T23:59:59"})
    assert r.status_code == 200
    detail = client.get(f"/api/surveys/{sid}").get_json()["survey"]
    assert detail["title"] == "新标题"
    assert detail["deadline"] is not None
    client.put(f"/api/surveys/{sid}", json={"deadline": ""})
    detail = client.get(f"/api/surveys/{sid}").get_json()["survey"]
    assert detail["deadline"] is None

    register_login(client, "bob2")
    assert client.get(f"/api/surveys/{sid}").status_code == 404


def test_add_questions_all_types(client):
    register_login(client, "carol")
    sid = create_survey(client, "题型测试")
    q1 = add_question(client, sid, {
        "qid": "q1", "type": "single", "title": "性别", "required": True,
        "options": [{"text": "男"}, {"text": "女"}]})
    q2 = add_question(client, sid, {
        "qid": "q2", "type": "multiple", "title": "喜欢的水果", "required": True,
        "options": [{"text": "苹果"}, {"text": "香蕉"}, {"text": "西瓜"}],
        "validation": {"min_select": 2, "max_select": 3}})
    q3 = add_question(client, sid, {
        "qid": "q3", "type": "text", "title": "意见", "required": False,
        "validation": {"min_len": 2, "max_len": 50}})
    q4 = add_question(client, sid, {
        "qid": "q4", "type": "number", "title": "年龄", "required": True,
        "validation": {"integer": True, "min": 0, "max": 120}})
    detail = client.get(f"/api/surveys/{sid}").get_json()["survey"]
    assert [q["qid"] for q in detail["questions"]] == [q1, q2, q3, q4]
    assert detail["questions"][1]["validation"] == {"min_select": 2, "max_select": 3}

    assert client.post(f"/api/surveys/{sid}/questions",
                       json={"qid": "q1", "type": "single", "title": "重复",
                             "options": [{"text": "A"}]}).status_code == 400

    r = client.put(f"/api/surveys/{sid}/questions/{q4}",
                   json={"qid": "q4", "type": "number", "title": "年龄(更新)", "required": False,
                         "validation": {"integer": True, "max": 150}})
    assert r.status_code == 200
    detail = client.get(f"/api/surveys/{sid}").get_json()["survey"]
    q4_new = next(q for q in detail["questions"] if q["qid"] == q4)
    assert q4_new["title"] == "年龄(更新)"
    assert q4_new["validation"] == {"integer": True, "max": 150}

    assert client.delete(f"/api/surveys/{sid}/questions/{q3}").status_code == 200
    detail = client.get(f"/api/surveys/{sid}").get_json()["survey"]
    assert len(detail["questions"]) == 3


def test_publish_public_close(client):
    register_login(client, "dave")
    sid = create_survey(client, "发布测试")
    add_question(client, sid, {"qid": "q1", "type": "single", "title": "Q1",
                               "options": [{"text": "A"}]})
    assert client.get(f"/api/surveys/{sid}/public").status_code == 404
    assert client.post(f"/api/surveys/{sid}/publish").status_code == 200
    pub = client.get(f"/api/surveys/{sid}/public").get_json()["survey"]
    assert pub["title"] == "发布测试" and "owner_id" not in pub
    assert client.post(f"/api/surveys/{sid}/close").status_code == 200
    register_login(client, "dave2")
    r = client.post(f"/api/surveys/{sid}/responses", json={"answers": [{"qid": "x", "option_ids": []}]})
    assert r.status_code == 400 and "未发布" in r.get_json()["error"]


def test_submit_requires_login(client):
    register_login(client, "erin")
    sid = create_survey(client, "需要登录")
    add_question(client, sid, {"qid": "q1", "type": "single", "title": "Q", "required": True,
                               "options": [{"text": "A"}]})
    client.post(f"/api/surveys/{sid}/publish")
    client.post("/api/logout")
    r = client.post(f"/api/surveys/{sid}/responses", json={"answers": []})
    assert r.status_code == 401


def test_submit_validation_errors(client):
    register_login(client, "frank")
    sid = create_survey(client, "校验测试")
    add_question(client, sid, {"qid": "q1", "type": "single", "title": "必答单选", "required": True,
                               "options": [{"text": "A"}, {"text": "B"}]})
    add_question(client, sid, {"qid": "q2", "type": "multiple", "title": "限选多选", "required": True,
                               "options": [{"text": "x"}, {"text": "y"}, {"text": "z"}],
                               "validation": {"exact_select": 2}})
    add_question(client, sid, {"qid": "q3", "type": "number", "title": "整数年龄", "required": True,
                               "validation": {"integer": True, "min": 0, "max": 120}})
    client.post(f"/api/surveys/{sid}/publish")

    r = client.post(f"/api/surveys/{sid}/responses", json={"answers": [
        {"qid": "q2", "option_ids": ["o1", "o2"]},
        {"qid": "q3", "number": 20}]})
    assert r.status_code == 400
    assert "q1" in r.get_json()["errors"]

    r = client.post(f"/api/surveys/{sid}/responses", json={"answers": [
        {"qid": "q1", "option_ids": ["o1"]},
        {"qid": "q2", "option_ids": ["o1"]},
        {"qid": "q3", "number": 20}]})
    assert r.status_code == 400
    assert "必须选择 2 个选项" in r.get_json()["errors"]["q2"]

    r = client.post(f"/api/surveys/{sid}/responses", json={"answers": [
        {"qid": "q1", "option_ids": ["o1"]},
        {"qid": "q2", "option_ids": ["o1", "o2"]},
        {"qid": "q3", "number": 25.5}]})
    assert r.status_code == 400
    assert "必须为整数" in r.get_json()["errors"]["q3"]

    r = client.post(f"/api/surveys/{sid}/responses", json={"answers": [
        {"qid": "q1", "option_ids": ["o1"]},
        {"qid": "q2", "option_ids": ["o1", "o2"]},
        {"qid": "q3", "number": 20}]})
    assert r.status_code == 200


def test_submit_jump_end_to_end(client):
    register_login(client, "grace")
    sid = create_survey(client, "跳转测试")
    add_question(client, sid, {"qid": "q1", "type": "single", "title": "选择去向", "required": True,
                               "options": [{"text": "去第3题"}, {"text": "顺序走"}],
                               "jumps": [{"condition": {"option_id": "o1"}, "target_qid": "q3"}]})
    add_question(client, sid, {"qid": "q2", "type": "single", "title": "中间必答", "required": True,
                               "options": [{"text": "M"}]})
    add_question(client, sid, {"qid": "q3", "type": "single", "title": "终点题", "required": True,
                               "options": [{"text": "Z"}]})
    client.post(f"/api/surveys/{sid}/publish")

    r = client.post(f"/api/surveys/{sid}/responses", json={"answers": [
        {"qid": "q1", "option_ids": ["o1"]},
        {"qid": "q3", "option_ids": ["o1"]}]})
    assert r.status_code == 200

    r = client.post(f"/api/surveys/{sid}/responses", json={"answers": [
        {"qid": "q1", "option_ids": ["o2"]},
        {"qid": "q3", "option_ids": ["o1"]}]})
    assert r.status_code == 400
    assert "q2" in r.get_json()["errors"]


# 统计这里最容易出问题，多写几个断言
def test_stats(client, db):
    register_login(client, "hank")
    sid = create_survey(client, "统计测试")
    add_question(client, sid, {"qid": "q1", "type": "single", "title": "性别",
                               "options": [{"text": "男"}, {"text": "女"}]})
    add_question(client, sid, {"qid": "q2", "type": "multiple", "title": "水果",
                               "options": [{"text": "苹果"}, {"text": "香蕉"}]})
    add_question(client, sid, {"qid": "q3", "type": "text", "title": "意见"})
    add_question(client, sid, {"qid": "q4", "type": "number", "title": "年龄",
                               "validation": {"integer": True, "max": 120}})
    client.post(f"/api/surveys/{sid}/publish")

    register_login(client, "hank2")
    submissions = [
        [{"qid": "q1", "option_ids": ["o1"]}, {"qid": "q2", "option_ids": ["o1", "o2"]},
         {"qid": "q3", "text": "很好"}, {"qid": "q4", "number": 20}],
        [{"qid": "q1", "option_ids": ["o1"]}, {"qid": "q2", "option_ids": ["o2"]},
         {"qid": "q3", "text": "一般般"}, {"qid": "q4", "number": 30}],
        [{"qid": "q1", "option_ids": ["o2"]}, {"qid": "q2", "option_ids": ["o1"]},
         {"qid": "q4", "number": 10}],
    ]
    for ans in submissions:
        assert client.post(f"/api/surveys/{sid}/responses",
                           json={"answers": ans}).status_code == 200

    login(client, "hank")
    stats = client.get(f"/api/surveys/{sid}/stats").get_json()
    assert stats["total_responses"] == 3
    qmap = {q["qid"]: q for q in stats["questions"]}
    single = qmap["q1"]
    assert single["total"] == 3
    assert {o["text"]: o["count"] for o in single["options"]} == {"男": 2, "女": 1}
    multi = qmap["q2"]
    assert multi["total_selections"] == 4
    assert {o["text"]: o["count"] for o in multi["options"]} == {"苹果": 2, "香蕉": 2}
    assert qmap["q3"]["texts"] == ["很好", "一般般"]
    num = qmap["q4"]
    assert num["answered"] == 3 and num["avg"] == 20.0 and num["min"] == 10 and num["max"] == 30
    one = client.get(f"/api/surveys/{sid}/stats/q1").get_json()["stats"]
    assert one["total"] == 3


def test_anonymous_response_hides_user(client, db):
    register_login(client, "ivan")
    sid = create_survey(client, "匿名问卷", anon=True)
    add_question(client, sid, {"qid": "q1", "type": "single", "title": "Q",
                               "options": [{"text": "A"}]})
    client.post(f"/api/surveys/{sid}/publish")
    register_login(client, "ivan2")
    client.post(f"/api/surveys/{sid}/responses",
                json={"answers": [{"qid": "q1", "option_ids": ["o1"]}]})
    resp = db.responses.find_one({"survey_id": db.surveys.find_one({"sid": sid})["_id"]})
    assert resp["user_id"] is None and resp["anonymous"] is True

    register_login(client, "ivan3")
    sid2 = create_survey(client, "实名问卷", anon=False)
    add_question(client, sid2, {"qid": "q1", "type": "single", "title": "Q",
                                "options": [{"text": "A"}]})
    client.post(f"/api/surveys/{sid2}/publish")
    client.post(f"/api/surveys/{sid2}/responses",
                json={"answers": [{"qid": "q1", "option_ids": ["o1"]}]})
    resp2 = db.responses.find_one({"survey_id": db.surveys.find_one({"sid": sid2})["_id"]})
    assert resp2["user_id"] is not None and resp2["anonymous"] is False


def test_deadline_blocks_submission(client):
    register_login(client, "judy")
    sid = create_survey(client, "截止测试")
    add_question(client, sid, {"qid": "q1", "type": "single", "title": "Q",
                               "options": [{"text": "A"}]})
    past = (datetime.datetime.utcnow() - datetime.timedelta(days=1)).isoformat()
    client.put(f"/api/surveys/{sid}", json={"deadline": past})
    client.post(f"/api/surveys/{sid}/publish")
    register_login(client, "judy2")
    r = client.post(f"/api/surveys/{sid}/responses",
                    json={"answers": [{"qid": "q1", "option_ids": ["o1"]}]})
    assert r.status_code == 400 and "截止" in r.get_json()["error"]


def test_delete_survey(client, db):
    register_login(client, "ken")
    sid = create_survey(client, "删除测试")
    add_question(client, sid, {"qid": "q1", "type": "single", "title": "Q",
                               "options": [{"text": "A"}]})
    client.post(f"/api/surveys/{sid}/publish")
    survey_id = db.surveys.find_one({"sid": sid})["_id"]
    register_login(client, "ken2")
    client.post(f"/api/surveys/{sid}/responses",
                json={"answers": [{"qid": "q1", "option_ids": ["o1"]}]})
    login(client, "ken")
    assert client.delete(f"/api/surveys/{sid}").status_code == 200
    assert client.get(f"/api/surveys/{sid}").status_code == 404
    assert db.responses.count_documents({"survey_id": survey_id}) == 0
