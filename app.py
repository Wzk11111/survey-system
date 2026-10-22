# 问卷系统后端，功能都是作业要求的那些
# -*- coding: utf-8 -*-

import os
import re
import secrets
import string
import hashlib
import datetime

from flask import (Flask, request, session, jsonify, send_from_directory,
                   render_template)

from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError
from bson import ObjectId

MONGO_URI = os.environ.get("MONGO_URI", "mongodb://127.0.0.1:27017/")
MONGO_DB = os.environ.get("MONGO_DB", "survey_system")
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-change-me")

app = Flask(__name__, static_folder="static", static_url_path="/static")
app.secret_key = SECRET_KEY
app.config["JSON_AS_ASCII"] = False

client = MongoClient(MONGO_URI)
db = client[MONGO_DB]

USERS = db.users
SURVEYS = db.surveys
RESPONSES = db.responses


# 建索引，测试清库后要重新跑，不然重复注册会挂
def ensure_indexes():
    USERS.create_index("username", unique=True)
    SURVEYS.create_index("sid", unique=True)
    SURVEYS.create_index("owner_id")
    RESPONSES.create_index("survey_id")
    RESPONSES.create_index([("survey_id", 1), ("submitted_at", -1)])


ensure_indexes()


def gen_sid(length=6):
    alphabet = string.ascii_letters + string.digits
    for _ in range(20):
        code = "".join(secrets.choice(alphabet) for _ in range(length))
        if not SURVEYS.find_one({"sid": code}):
            return code
    raise RuntimeError("短码生成失败")


def hash_password(password, salt=None):
    if salt is None:
        salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                                 salt.encode("utf-8"), 100_000)
    return salt, digest.hex()


def current_user():
    uid = session.get("uid")
    if not uid:
        return None
    return USERS.find_one({"_id": ObjectId(uid)})


def login_required(fn):
    from functools import wraps

    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = current_user()
        if not user:
            return jsonify({"ok": False, "error": "请先登录"}), 401
        return fn(user, *args, **kwargs)

    return wrapper


def get_survey_or_404(sid):
    survey = SURVEYS.find_one({"sid": sid})
    if not survey:
        return None
    return survey


def sanitize_survey(survey):
    s = dict(survey)
    s["_id"] = str(s["_id"])
    s.pop("owner_id", None)
    return s


# 跳转规则：答了什么跳哪题，规则存在问卷数据里
def evaluate_jump(question, answer):
    rules = question.get("jumps") or []
    if not rules or answer is None:
        return None

    qtype = question.get("type")

    if qtype == "single":
        selected = set(answer.get("option_ids") or [])
        for rule in rules:
            cond = rule.get("condition") or {}
            if cond.get("option_id") in selected:
                return rule.get("target_qid")

    elif qtype == "multiple":
        selected = set(answer.get("option_ids") or [])
        for rule in rules:
            cond = rule.get("condition") or {}
            if cond.get("contains") and set(cond["contains"]) <= selected:
                return rule.get("target_qid")
            if cond.get("not_contains") and not (set(cond["not_contains"]) & selected):
                return rule.get("target_qid")

    elif qtype == "number":
        value = answer.get("number")
        for rule in rules:
            cond = rule.get("condition") or {}
            op, ref = cond.get("op"), cond.get("value")
            if value is None or ref is None:
                continue
            if op == "==" and value == ref:
                return rule.get("target_qid")
            if op == "!=" and value != ref:
                return rule.get("target_qid")
            if op == ">" and value > ref:
                return rule.get("target_qid")
            if op == ">=" and value >= ref:
                return rule.get("target_qid")
            if op == "<" and value < ref:
                return rule.get("target_qid")
            if op == "<=" and value <= ref:
                return rule.get("target_qid")
    return None


def compute_walk(survey, answers_by_qid):
    questions = survey.get("questions") or []
    index = 0
    visited = []
    while 0 <= index < len(questions):
        q = questions[index]
        visited.append(q["qid"])
        ans = answers_by_qid.get(q["qid"])
        if ans is not None:
            target = evaluate_jump(q, ans)
            if target:
                idx = next((i for i, qq in enumerate(questions)
                            if qq["qid"] == target), None)
                if idx is not None:
                    index = idx
                    continue
        index += 1
    return visited


def validate_answer(question, answer):
    qtype = question.get("type")
    required = bool(question.get("required"))
    v = question.get("validation") or {}

    if qtype in ("single", "multiple"):
        selected = answer.get("option_ids") or []
        valid_oids = {o.get("oid") for o in question.get("options") or []}
        if qtype == "single" and len(selected) > 1:
            return "单选题只能选择一个选项"
        if required and not selected:
            return "该题为必答题"
        if qtype == "multiple" and selected:
            n = len(selected)
            if v.get("exact_select") is not None and n != v["exact_select"]:
                return f"本题必须选择 {v['exact_select']} 个选项（当前 {n} 个）"
            if v.get("min_select") is not None and n < v["min_select"]:
                return f"本题至少选择 {v['min_select']} 个选项（当前 {n} 个）"
            if v.get("max_select") is not None and n > v["max_select"]:
                return f"本题最多选择 {v['max_select']} 个选项（当前 {n} 个）"

    elif qtype == "text":
        text = answer.get("text") or ""
        if required and not text.strip():
            return "该题为必答题"
        n = len(text)
        if v.get("min_len") is not None and n < v["min_len"]:
            return f"最少输入 {v['min_len']} 个字（当前 {n} 字）"
        if v.get("max_len") is not None and n > v["max_len"]:
            return f"最多输入 {v['max_len']} 个字（当前 {n} 字）"

    elif qtype == "number":
        value = answer.get("number")
        if value is None:
            if required:
                return "该题为必答题"
            return None
        if v.get("integer") and float(value) != int(value):
            return "必须为整数"
        if v.get("min") is not None and value < v["min"]:
            return f"最小值不能小于 {v['min']}"
        if v.get("max") is not None and value > v["max"]:
            return f"最大值不能大于 {v['max']}"
    return None


# 提交前整体校验一遍，必答题没答的直接拦下
def validate_submission(survey, answers):
    qmap = {q["qid"]: q for q in survey.get("questions") or []}
    answers_by_qid = {a["qid"]: a for a in answers}

    errors = {}
    for qid, q in qmap.items():
        ans = answers_by_qid.get(qid)
        if ans is not None:
            msg = validate_answer(q, ans)
            if msg:
                errors[qid] = msg

    visited = compute_walk(survey, answers_by_qid)
    for qid in visited:
        q = qmap.get(qid)
        if q and q.get("required") and qid not in answers_by_qid:
            errors[qid] = "该题为必答题，未作答"
    return (not errors), errors


def stats_for_question(survey, q):
    qid = q["qid"]
    qtype = q["type"]
    qs = [ObjectId(survey["_id"])] if isinstance(survey["_id"], str) else [survey["_id"]]

    total = RESPONSES.count_documents({
        "survey_id": survey["_id"],
        "answers.qid": qid,
    })

    result = {"qid": qid, "title": q["title"], "type": qtype, "total": total}

    if qtype in ("single", "multiple"):
        pipeline = [
            {"$match": {"survey_id": survey["_id"], "answers.qid": qid}},
            {"$unwind": "$answers"},
            {"$match": {"answers.qid": qid}},
            {"$unwind": "$answers.option_ids"},
            {"$group": {"_id": "$answers.option_ids", "count": {"$sum": 1}}},
        ]
        option_counts = {str(d["_id"]): d["count"] for d in RESPONSES.aggregate(pipeline)}
        result["options"] = [
            {"oid": o.get("oid"), "text": o.get("text"),
             "count": option_counts.get(o.get("oid"), 0)}
            for o in (q.get("options") or [])
        ]
        result["total_selections"] = sum(option_counts.values())

    elif qtype == "text":
        texts = RESPONSES.aggregate([
            {"$match": {"survey_id": survey["_id"], "answers.qid": qid}},
            {"$unwind": "$answers"},
            {"$match": {"answers.qid": qid}},
            {"$project": {"_id": 0, "text": "$answers.text"}},
        ])
        result["texts"] = [d["text"] for d in texts]

    elif qtype == "number":
        pipeline = [
            {"$match": {"survey_id": survey["_id"], "answers.qid": qid}},
            {"$unwind": "$answers"},
            {"$match": {"answers.qid": qid, "answers.number": {"$ne": None}}},
            {"$group": {
                "_id": None,
                "count": {"$sum": 1},
                "avg": {"$avg": "$answers.number"},
                "min": {"$min": "$answers.number"},
                "max": {"$max": "$answers.number"},
            }},
        ]
        agg = list(RESPONSES.aggregate(pipeline))
        if agg:
            d = agg[0]
            result.update({
                "answered": d["count"],
                "avg": round(d["avg"], 2) if d["avg"] is not None else None,
                "min": d["min"],
                "max": d["max"],
            })
        else:
            result.update({"answered": 0, "avg": None, "min": None, "max": None})
    return result


@app.route("/")
def index_page():
    return send_from_directory("static", "index.html")


@app.route("/dashboard")
def dashboard_page():
    return send_from_directory("static", "dashboard.html")


@app.route("/editor")
def editor_page():
    return send_from_directory("static", "editor.html")


@app.route("/stats")
def stats_page():
    return send_from_directory("static", "stats.html")


@app.route("/survey/<sid>")
def fill_page(sid):
    return send_from_directory("static", "fill.html")


@app.route("/api/register", methods=["POST"])
def register():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    if not re.fullmatch(r"[\w\u4e00-\u9fa5]{2,20}", username):
        return jsonify({"ok": False, "error": "用户名需为 2-20 位字母/数字/下划线/中文"}), 400
    if len(password) < 6:
        return jsonify({"ok": False, "error": "密码至少 6 位"}), 400
    salt, digest = hash_password(password)
    try:
        USERS.insert_one({
            "username": username,
            "password_hash": digest,
            "salt": salt,
            "created_at": datetime.datetime.utcnow(),
        })
    except DuplicateKeyError:
        return jsonify({"ok": False, "error": "用户名已存在"}), 409
    return jsonify({"ok": True})


@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    user = USERS.find_one({"username": username})
    if not user:
        return jsonify({"ok": False, "error": "用户名或密码错误"}), 401
    _, digest = hash_password(password, user["salt"])
    if digest != user["password_hash"]:
        return jsonify({"ok": False, "error": "用户名或密码错误"}), 401
    session["uid"] = str(user["_id"])
    return jsonify({"ok": True, "username": user["username"]})


@app.route("/api/logout", methods=["POST"])
def logout():
    session.pop("uid", None)
    return jsonify({"ok": True})


@app.route("/api/me")
def me():
    user = current_user()
    if not user:
        return jsonify({"ok": False}), 401
    return jsonify({"ok": True, "username": user["username"]})


@app.route("/api/surveys", methods=["GET"])
@login_required
def list_surveys(user):
    surveys = SURVEYS.find({"owner_id": user["_id"]}).sort("created_at", -1)
    items = []
    for s in surveys:
        items.append({
            "sid": s["sid"],
            "title": s.get("title", ""),
            "description": s.get("description", ""),
            "status": s.get("status", "draft"),
            "allow_anonymous": s.get("allow_anonymous", False),
            "deadline": s.get("deadline"),
            "question_count": len(s.get("questions") or []),
            "response_count": RESPONSES.count_documents({"survey_id": s["_id"]}),
            "created_at": s.get("created_at"),
        })
    return jsonify({"ok": True, "surveys": items})


@app.route("/api/surveys", methods=["POST"])
@login_required
def create_survey(user):
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    if not title:
        return jsonify({"ok": False, "error": "问卷标题不能为空"}), 400
    survey = {
        "sid": gen_sid(),
        "owner_id": user["_id"],
        "title": title,
        "description": (data.get("description") or "").strip(),
        "allow_anonymous": bool(data.get("allow_anonymous")),
        "status": "draft",
        "deadline": None,
        "questions": [],
        "created_at": datetime.datetime.utcnow(),
        "updated_at": datetime.datetime.utcnow(),
    }
    SURVEYS.insert_one(survey)
    return jsonify({"ok": True, "sid": survey["sid"]})


@app.route("/api/surveys/<sid>", methods=["GET"])
@login_required
def get_survey(user, sid):
    survey = get_survey_or_404(sid)
    if not survey or survey["owner_id"] != user["_id"]:
        return jsonify({"ok": False, "error": "问卷不存在"}), 404
    return jsonify({"ok": True, "survey": sanitize_survey(survey)})


@app.route("/api/surveys/<sid>", methods=["PUT"])
@login_required
def update_survey(user, sid):
    survey = get_survey_or_404(sid)
    if not survey or survey["owner_id"] != user["_id"]:
        return jsonify({"ok": False, "error": "问卷不存在"}), 404
    data = request.get_json(silent=True) or {}
    patch = {}
    if "title" in data:
        title = (data.get("title") or "").strip()
        if not title:
            return jsonify({"ok": False, "error": "问卷标题不能为空"}), 400
        patch["title"] = title
    if "description" in data:
        patch["description"] = (data.get("description") or "").strip()
    if "allow_anonymous" in data:
        patch["allow_anonymous"] = bool(data["allow_anonymous"])
    if "deadline" in data:
        deadline = data.get("deadline")
        if deadline is None or deadline == "":
            patch["deadline"] = None
        else:
            try:
                patch["deadline"] = datetime.datetime.fromisoformat(deadline)
            except ValueError:
                return jsonify({"ok": False, "error": "截止时间格式错误"}), 400
    patch["updated_at"] = datetime.datetime.utcnow()
    SURVEYS.update_one({"_id": survey["_id"]}, {"$set": patch})
    return jsonify({"ok": True})


@app.route("/api/surveys/<sid>", methods=["DELETE"])
@login_required
def delete_survey(user, sid):
    survey = get_survey_or_404(sid)
    if not survey or survey["owner_id"] != user["_id"]:
        return jsonify({"ok": False, "error": "问卷不存在"}), 404
    SURVEYS.delete_one({"_id": survey["_id"]})
    RESPONSES.delete_many({"survey_id": survey["_id"]})
    return jsonify({"ok": True})


@app.route("/api/surveys/<sid>/publish", methods=["POST"])
@login_required
def publish_survey(user, sid):
    survey = get_survey_or_404(sid)
    if not survey or survey["owner_id"] != user["_id"]:
        return jsonify({"ok": False, "error": "问卷不存在"}), 404
    SURVEYS.update_one({"_id": survey["_id"]},
                       {"$set": {"status": "published", "updated_at": datetime.datetime.utcnow()}})
    return jsonify({"ok": True})


@app.route("/api/surveys/<sid>/close", methods=["POST"])
@login_required
def close_survey(user, sid):
    survey = get_survey_or_404(sid)
    if not survey or survey["owner_id"] != user["_id"]:
        return jsonify({"ok": False, "error": "问卷不存在"}), 404
    SURVEYS.update_one({"_id": survey["_id"]},
                       {"$set": {"status": "closed", "updated_at": datetime.datetime.utcnow()}})
    return jsonify({"ok": True})


def normalize_question(data):
    qtype = data.get("type")
    if qtype not in ("single", "multiple", "text", "number"):
        raise ValueError("不支持的题型")
    q = {
        "qid": data.get("qid") or secrets.token_hex(4),
        "type": qtype,
        "title": (data.get("title") or "").strip() or "未命名题目",
        "required": bool(data.get("required")),
        "jumps": [],
    }
    if qtype in ("single", "multiple"):
        options = []
        for i, o in enumerate(data.get("options") or [], start=1):
            text = (o.get("text") if isinstance(o, dict) else str(o)).strip()
            if not text:
                continue
            options.append({"oid": (o.get("oid") if isinstance(o, dict) and o.get("oid") else f"o{i}"),
                            "text": text})
        if not options:
            raise ValueError("选择题至少需要一个选项")
        q["options"] = options
        if qtype == "multiple":
            v = {}
            for key in ("min_select", "max_select", "exact_select"):
                val = data.get("validation", {}).get(key)
                if val is not None and val != "":
                    v[key] = int(val)
            q["validation"] = v
    elif qtype == "text":
        v = {}
        for key in ("min_len", "max_len"):
            val = data.get("validation", {}).get(key)
            if val is not None and val != "":
                v[key] = int(val)
        q["validation"] = v
    elif qtype == "number":
        v = {}
        for key in ("min", "max"):
            val = data.get("validation", {}).get(key)
            if val is not None and val != "":
                v[key] = float(val)
        if data.get("validation", {}).get("integer"):
            v["integer"] = True
        q["validation"] = v
    for rule in data.get("jumps") or []:
        target = rule.get("target_qid")
        cond = rule.get("condition") or {}
        if not target:
            continue
        if qtype == "single" and cond.get("option_id"):
            q["jumps"].append({"condition": {"option_id": cond["option_id"]},
                               "target_qid": target})
        elif qtype == "multiple" and (cond.get("contains") or cond.get("not_contains")):
            q["jumps"].append({"condition": {"contains": cond.get("contains") or [],
                                             "not_contains": cond.get("not_contains") or []},
                               "target_qid": target})
        elif qtype == "number" and cond.get("op") and cond.get("value") is not None:
            q["jumps"].append({"condition": {"op": cond["op"], "value": float(cond["value"])},
                               "target_qid": target})
    return q


@app.route("/api/surveys/<sid>/questions", methods=["POST"])
@login_required
def add_question(user, sid):
    survey = get_survey_or_404(sid)
    if not survey or survey["owner_id"] != user["_id"]:
        return jsonify({"ok": False, "error": "问卷不存在"}), 404
    try:
        q = normalize_question(request.get_json(silent=True) or {})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    existing = [x["qid"] for x in (survey.get("questions") or [])]
    if q["qid"] in existing:
        return jsonify({"ok": False, "error": "题目编号已存在"}), 400
    SURVEYS.update_one({"_id": survey["_id"]},
                       {"$push": {"questions": q},
                        "$set": {"updated_at": datetime.datetime.utcnow()}})
    return jsonify({"ok": True, "qid": q["qid"]})


@app.route("/api/surveys/<sid>/questions/<qid>", methods=["PUT"])
@login_required
def update_question(user, sid, qid):
    survey = get_survey_or_404(sid)
    if not survey or survey["owner_id"] != user["_id"]:
        return jsonify({"ok": False, "error": "问卷不存在"}), 404
    questions = survey.get("questions") or []
    if qid not in [q["qid"] for q in questions]:
        return jsonify({"ok": False, "error": "题目不存在"}), 404
    data = request.get_json(silent=True) or {}
    data["qid"] = qid
    try:
        q = normalize_question(data)
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    SURVEYS.update_one(
        {"_id": survey["_id"], "questions.qid": qid},
        {"$set": {"questions.$": q, "updated_at": datetime.datetime.utcnow()}})
    return jsonify({"ok": True})


@app.route("/api/surveys/<sid>/questions/<qid>", methods=["DELETE"])
@login_required
def delete_question(user, sid, qid):
    survey = get_survey_or_404(sid)
    if not survey or survey["owner_id"] != user["_id"]:
        return jsonify({"ok": False, "error": "问卷不存在"}), 404
    SURVEYS.update_one(
        {"_id": survey["_id"]},
        {"$pull": {"questions": {"qid": qid}},
         "$set": {"updated_at": datetime.datetime.utcnow()}})
    return jsonify({"ok": True})


@app.route("/api/surveys/<sid>/public", methods=["GET"])
def public_survey(sid):
    survey = get_survey_or_404(sid)
    if not survey or survey.get("status") != "published":
        return jsonify({"ok": False, "error": "问卷未发布或不存在"}), 404
    return jsonify({"ok": True, "survey": sanitize_survey(survey)})


@app.route("/api/surveys/<sid>/responses", methods=["POST"])
@login_required
def submit_response(user, sid):
    survey = get_survey_or_404(sid)
    if not survey:
        return jsonify({"ok": False, "error": "问卷不存在"}), 404
    if survey.get("status") != "published":
        return jsonify({"ok": False, "error": "问卷未发布"}), 400
    if survey.get("deadline") and datetime.datetime.utcnow() > survey["deadline"]:
        return jsonify({"ok": False, "error": "问卷已过截止时间"}), 400

    data = request.get_json(silent=True) or {}
    answers = data.get("answers") or []
    ok, errors = validate_submission(survey, answers)
    if not ok:
        return jsonify({"ok": False, "error": "填写不合法", "errors": errors}), 400

# 匿名问卷不记谁填的，实名的才记
    respondent_id = None if survey.get("allow_anonymous") else user["_id"]
    RESPONSES.insert_one({
        "survey_id": survey["_id"],
        "user_id": respondent_id,
        "anonymous": bool(survey.get("allow_anonymous")),
        "answers": answers,
        "submitted_at": datetime.datetime.utcnow(),
    })
    return jsonify({"ok": True})


@app.route("/api/surveys/<sid>/stats", methods=["GET"])
@login_required
def survey_stats(user, sid):
    survey = get_survey_or_404(sid)
    if not survey or survey["owner_id"] != user["_id"]:
        return jsonify({"ok": False, "error": "问卷不存在"}), 404
    total = RESPONSES.count_documents({"survey_id": survey["_id"]})
    questions = [stats_for_question(survey, q) for q in (survey.get("questions") or [])]
    return jsonify({"ok": True, "total_responses": total, "questions": questions})


@app.route("/api/surveys/<sid>/stats/<qid>", methods=["GET"])
@login_required
def question_stats(user, sid, qid):
    survey = get_survey_or_404(sid)
    if not survey or survey["owner_id"] != user["_id"]:
        return jsonify({"ok": False, "error": "问卷不存在"}), 404
    q = next((x for x in (survey.get("questions") or []) if x["qid"] == qid), None)
    if not q:
        return jsonify({"ok": False, "error": "题目不存在"}), 404
    return jsonify({"ok": True, "stats": stats_for_question(survey, q)})


if __name__ == "__main__":
    print(f"问卷系统已启动: http://127.0.0.1:5000  (MongoDB: {MONGO_URI}{MONGO_DB})")
    app.run(host="127.0.0.1", port=5000, debug=False)
