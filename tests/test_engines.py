# 跳转和校验的逻辑抽出来单独测，好定位问题
import pytest
from app import evaluate_jump, compute_walk, validate_answer, validate_submission


def test_jump_single_match():
    q = {"type": "single", "jumps": [{"condition": {"option_id": "o1"}, "target_qid": "q5"}]}
    assert evaluate_jump(q, {"option_ids": ["o1"]}) == "q5"
    assert evaluate_jump(q, {"option_ids": ["o2"]}) is None
    assert evaluate_jump(q, None) is None


def test_jump_multiple_contains():
    q = {"type": "multiple",
         "jumps": [{"condition": {"contains": ["o1", "o3"]}, "target_qid": "q8"}]}
    assert evaluate_jump(q, {"option_ids": ["o1", "o3", "o2"]}) == "q8"
    assert evaluate_jump(q, {"option_ids": ["o1", "o2"]}) is None


def test_jump_number_ops():
    q = {"type": "number", "jumps": [
        {"condition": {"op": ">=", "value": 18}, "target_qid": "q10"},
        {"condition": {"op": "<", "value": 18}, "target_qid": "q11"},
    ]}
    assert evaluate_jump(q, {"number": 20}) == "q10"
    assert evaluate_jump(q, {"number": 18}) == "q10"
    assert evaluate_jump(q, {"number": 12}) == "q11"


# 跳转路径算得对不对，这里最容易错
def test_walk_follows_jumps():
    survey = {"questions": [
        {"qid": "q1", "type": "single", "jumps": [
            {"condition": {"option_id": "A"}, "target_qid": "q5"},
            {"condition": {"option_id": "B"}, "target_qid": "q3"}]},
        {"qid": "q2", "type": "single", "jumps": []},
        {"qid": "q3", "type": "single", "jumps": []},
        {"qid": "q4", "type": "single", "jumps": []},
        {"qid": "q5", "type": "single", "jumps": []},
    ]}
    walk = compute_walk(survey, {"q1": {"option_ids": ["A"]}})
    assert walk == ["q1", "q5"]
    walk = compute_walk(survey, {"q1": {"option_ids": ["B"]}})
    assert walk == ["q1", "q3", "q4", "q5"]
    walk = compute_walk(survey, {})
    assert walk == ["q1", "q2", "q3", "q4", "q5"]


def test_validate_single():
    q = {"type": "single", "required": True, "options": [{"oid": "o1"}, {"oid": "o2"}]}
    assert validate_answer(q, {"option_ids": ["o1"]}) is None
    assert validate_answer(q, {"option_ids": []}) == "该题为必答题"
    assert validate_answer(q, {"option_ids": ["o1", "o2"]}) == "单选题只能选择一个选项"


def test_validate_multiple_limits():
    q = {"type": "multiple", "required": True,
         "validation": {"min_select": 2, "max_select": 3},
         "options": [{"oid": "o1"}, {"oid": "o2"}, {"oid": "o3"}, {"oid": "o4"}]}
    assert validate_answer(q, {"option_ids": ["o1", "o2"]}) is None
    assert validate_answer(q, {"option_ids": ["o1"]}) == "本题至少选择 2 个选项（当前 1 个）"
    assert validate_answer(q, {"option_ids": ["o1", "o2", "o3", "o4"]}) == "本题最多选择 3 个选项（当前 4 个）"
    q2 = {"type": "multiple", "required": True, "validation": {"exact_select": 2},
          "options": [{"oid": "o1"}, {"oid": "o2"}, {"oid": "o3"}]}
    assert validate_answer(q2, {"option_ids": ["o1", "o2"]}) is None
    assert validate_answer(q2, {"option_ids": ["o1", "o2", "o3"]}) == "本题必须选择 2 个选项（当前 3 个）"


def test_validate_text_length():
    q = {"type": "text", "required": True, "validation": {"min_len": 2, "max_len": 10}}
    assert validate_answer(q, {"text": "你好呀"}) is None
    assert validate_answer(q, {"text": ""}) == "该题为必答题"
    assert validate_answer(q, {"text": "短"}) == "最少输入 2 个字（当前 1 字）"
    assert validate_answer(q, {"text": "一" * 11}) == "最多输入 10 个字（当前 11 字）"


def test_validate_number_range():
    q = {"type": "number", "required": True,
         "validation": {"integer": True, "min": 0, "max": 120}}
    assert validate_answer(q, {"number": 25}) is None
    assert validate_answer(q, {"number": 25.5}) == "必须为整数"
    assert validate_answer(q, {"number": -1}) == "最小值不能小于 0"
    assert validate_answer(q, {"number": 121}) == "最大值不能大于 120"
    assert validate_answer(q, {}) == "该题为必答题"


def test_validate_submission_required_and_jump():
    survey = {"questions": [
        {"qid": "q1", "type": "single", "required": True,
         "options": [{"oid": "A"}, {"oid": "B"}],
         "jumps": [{"condition": {"option_id": "A"}, "target_qid": "q3"}]},
        {"qid": "q2", "type": "single", "required": True, "options": [{"oid": "X"}], "jumps": []},
        {"qid": "q3", "type": "single", "required": True, "options": [{"oid": "Y"}], "jumps": []},
    ]}
    ok, errs = validate_submission(survey, [
        {"qid": "q1", "option_ids": ["A"]},
        {"qid": "q3", "option_ids": ["Y"]},
    ])
    assert ok and errs == {}
    ok, errs = validate_submission(survey, [
        {"qid": "q1", "option_ids": ["B"]},
        {"qid": "q3", "option_ids": ["Y"]},
    ])
    assert not ok and "q2" in errs
    ok, errs = validate_submission(survey, [{"qid": "q3", "option_ids": ["Y"]}])
    assert not ok and "q1" in errs
