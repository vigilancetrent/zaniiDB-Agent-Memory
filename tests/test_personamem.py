from zanii_memory.personamem import ANSWER_RE, _cosine, _parse_options, format_report


def test_cosine():
    assert abs(_cosine([1, 0], [1, 0]) - 1.0) < 1e-9
    assert abs(_cosine([1, 0], [0, 1])) < 1e-9


def test_parse_options_json_and_python_repr():
    assert _parse_options('["(a) yes", "(b) no"]') == ["(a) yes", "(b) no"]
    assert _parse_options("['(a) it\\'s fine', '(b) no']") == ["(a) it's fine", "(b) no"]


def test_answer_regex():
    assert ANSWER_RE.search("(c)").group(1) == "c"
    assert ANSWER_RE.search("I pick (B) because...").group(1).lower() == "b"
    assert ANSWER_RE.search("no label here") is None


def test_format_report():
    text = format_report(
        {
            "size": "32k",
            "questions": 15,
            "contexts": 1,
            "accuracy": 0.8,
            "baseline_accuracy": 0.4,
            "by_type": {"recall_user_shared_facts": "4/5"},
        }
    )
    assert "80.0%" in text and "40.0%" in text and "recall_user_shared_facts: 4/5" in text
