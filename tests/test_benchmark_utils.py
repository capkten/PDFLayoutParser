from hexai_pdf_parser.benchmark_utils import extract_model_profile
from hexai_pdf_parser.benchmark_utils import resolve_model_dir
from hexai_pdf_parser.benchmark_utils import summarize_timings


def test_summarize_timings_reports_basic_stats():
    summary = summarize_timings([1.0, 2.0, 3.0])

    assert summary == {
        "count": 3,
        "total": 6.0,
        "mean": 2.0,
        "min": 1.0,
        "max": 3.0,
    }


def test_resolve_model_dir_prefers_override():
    assert resolve_model_dir("default", r"D:\models\plus") == r"D:\models\plus"
    assert resolve_model_dir("default", None) == "default"


def test_extract_model_profile_reads_resize_and_labels():
    profile = extract_model_profile(
        {
            "Global": {"model_name": "PP-DocLayout_plus-L"},
            "draw_threshold": 0.5,
            "layout_nms": True,
            "Preprocess": [
                {"type": "Resize", "target_size": [800, 800], "keep_ratio": False},
                {
                    "type": "NormalizeImage",
                    "norm_type": "none",
                    "mean": [0.0, 0.0, 0.0],
                    "std": [1.0, 1.0, 1.0],
                },
            ],
            "label_list": ["text", "table", "image"],
        }
    )

    assert profile["model_name"] == "PP-DocLayout_plus-L"
    assert profile["draw_threshold"] == 0.5
    assert profile["layout_nms"] is True
    assert profile["target_size"] == (800, 800)
    assert profile["keep_ratio"] is False
    assert profile["normalize"] == "none"
    assert profile["mean"] == (0.0, 0.0, 0.0)
    assert profile["std"] == (1.0, 1.0, 1.0)
    assert profile["label_list"] == ["text", "table", "image"]
