from pathlib import Path

import pytest

from kb import evaluate
from kb.evaluate import Case, matches, report, run


def test_example_file_loads():
    cases = evaluate.load(Path("eval/questions.example.yaml"))
    assert len(cases) == 5 and all(c.expect for c in cases)


def test_load_rejects_case_without_expect(tmp_path):
    f = tmp_path / "q.yaml"
    f.write_text("- q: hello\n")
    with pytest.raises(ValueError, match="case 1"):
        evaluate.load(f)


def test_matching_rules():
    r = {
        "item_id": 7,
        "title": "Тестовое письмо",
        "summary": "about SMTP forwarding",
        "excerpt": "",
        "locator": "https://t.me/x/5",
        "extra": {"context": [{"text": "Mirohost relay"}]},
    }
    assert matches(r, {"item_id": 7})
    assert matches(r, {"title_contains": "тестовое"})
    assert matches(r, {"text_contains": "smtp"})
    assert matches(r, {"text_contains": "mirohost"})  # context messages count
    assert matches(r, {"locator_contains": "t.me/x"})
    assert not matches(r, {"title_contains": "invoice"})


def test_report_recall_mrr_and_misses():
    cases = [
        Case("a", {"title_contains": "A"}),
        Case("b", {"title_contains": "B"}),
        Case("c", {"title_contains": "C"}),
    ]
    results = {"a": [{"title": "A"}], "b": [{"title": "x"}, {"title": "B"}], "c": [{"title": "x"}]}
    rep = report(run(cases, lambda q, k: results[q], k=10))
    assert rep["questions"] == 3
    assert rep["recall@10"] == pytest.approx(2 / 3, abs=0.001)
    assert rep["recall@1"] == pytest.approx(1 / 3, abs=0.001)
    assert rep["mrr"] == pytest.approx((1 + 0.5) / 3, abs=0.001)
    assert [m["q"] for m in rep["misses"]] == ["c"]
    assert rep["ranks"] == {"a": 1, "b": 2, "c": None}
