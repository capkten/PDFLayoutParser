from types import SimpleNamespace

import pytest

import fitz

from hexai_pdf_parser.core.models import BBox
import hexai_pdf_parser.ml.ml_table_detector as detector_module
from hexai_pdf_parser.ml.ml_table_detector import MLTableDetector


def test_expand_bbox_includes_directly_intersecting_words_once():
    result = MLTableDetector._expand_bbox_to_touching_words(
        BBox(10, 10, 20, 20),
        [(8, 12, 15, 18, "direct")],
    )

    assert result == BBox(8, 10, 20, 20)


def test_expand_bbox_does_not_chain_through_newly_expanded_words():
    result = MLTableDetector._expand_bbox_to_touching_words(
        BBox(10, 10, 20, 20),
        [(9, 12, 15, 18, "direct"), (4, 12, 9.5, 18, "chained")],
    )

    assert result == BBox(9, 10, 20, 20)


def test_expand_bbox_ignores_page_background_drawing():
    page = SimpleNamespace(
        rect=fitz.Rect(0, 0, 100, 100),
        get_drawings=lambda: [{"rect": fitz.Rect(0, 0, 100, 100)}],
    )

    result = MLTableDetector._expand_bbox_to_touching_words(
        BBox(10, 10, 20, 20),
        [(12, 12, 15, 18, "direct")],
        page=page,
    )

    assert result == BBox(10, 10, 20, 20)


def test_ml_table_detector_default_render_dpi_is_72():
    detector = MLTableDetector()
    assert detector.render_dpi == 72


def test_ml_table_detector_accepts_custom_render_dpi():
    detector = MLTableDetector(render_dpi=150)
    assert detector.render_dpi == 150


def test_ml_table_detector_reuses_shared_session():
    from hexai_pdf_parser.ml.ml_table_detector import clear_session_cache

    clear_session_cache()
    det1 = MLTableDetector()
    session1 = det1._load_session()

    det2 = MLTableDetector()
    session2 = det2._load_session()

    # Both instances must share the exact same underlying session
    assert session1 is session2

    # Even if det1 closes its local reference, det2 or new detectors still reuse the cache
    det1.close()
    assert det1._session is None

    det3 = MLTableDetector()
    assert det3._load_session() is session2


def test_clear_session_cache_forces_recreation():
    from hexai_pdf_parser.ml.ml_table_detector import clear_session_cache

    det1 = MLTableDetector()
    session1 = det1._load_session()

    clear_session_cache()

    det2 = MLTableDetector()
    session2 = det2._load_session()

    assert session1 is not session2


def test_auto_backend_uses_openvino_on_intel_when_available(monkeypatch):
    monkeypatch.setattr(detector_module.platform, "processor", lambda: "Intel(R) Core(TM)")
    monkeypatch.setattr(detector_module, "_openvino_is_available", lambda: True)

    assert detector_module._resolve_backend("auto") == "openvino"


def test_auto_backend_uses_cpu_on_non_intel_even_when_openvino_is_available(monkeypatch):
    monkeypatch.setattr(detector_module.platform, "processor", lambda: "AMD Ryzen")
    monkeypatch.setattr(
        detector_module.platform,
        "uname",
        lambda: SimpleNamespace(processor="AMD Ryzen"),
    )
    monkeypatch.setattr(detector_module, "_openvino_is_available", lambda: True)

    assert detector_module._resolve_backend("auto") == "cpu"


def test_auto_backend_uses_cpu_when_openvino_is_unavailable(monkeypatch):
    monkeypatch.setattr(detector_module.platform, "processor", lambda: "Intel(R) Core(TM)")
    monkeypatch.setattr(detector_module, "_openvino_is_available", lambda: False)

    assert detector_module._resolve_backend("auto") == "cpu"


def test_forced_openvino_requires_an_available_provider(monkeypatch):
    monkeypatch.setattr(detector_module, "_openvino_is_available", lambda: False)

    with pytest.raises(RuntimeError, match="OpenVINO"):
        detector_module._resolve_backend("openvino")


def test_session_cache_includes_provider_options(monkeypatch):
    class FakeSession:
        def __init__(self, providers):
            self._providers = providers

        def get_providers(self):
            return self._providers

    class FakeOrt:
        class GraphOptimizationLevel:
            ORT_DISABLE_ALL = "disabled"

        def __init__(self):
            self.calls = []

        def SessionOptions(self):
            return SimpleNamespace(graph_optimization_level=None)

        def InferenceSession(self, model_path, **kwargs):
            self.calls.append((model_path, kwargs))
            return FakeSession(kwargs["providers"])

    fake_ort = FakeOrt()
    monkeypatch.setattr(detector_module, "_require_onnxruntime", lambda **kwargs: fake_ort)
    detector_module.clear_session_cache()

    first = detector_module.get_shared_session(
        "model.onnx",
        providers=["OpenVINOExecutionProvider"],
        provider_options={"device_type": "CPU"},
    )
    second = detector_module.get_shared_session(
        "model.onnx",
        providers=["OpenVINOExecutionProvider"],
        provider_options={"device_type": "GPU"},
    )

    assert first is not second
    assert len(fake_ort.calls) == 2


def test_auto_backend_falls_back_to_cpu_when_openvino_session_fails(monkeypatch):
    class FakeSession:
        def __init__(self, providers):
            self._providers = providers

        def get_providers(self):
            return self._providers

    class FakeOrt:
        class GraphOptimizationLevel:
            ORT_DISABLE_ALL = "disabled"

        def __init__(self):
            self.calls = []

        def SessionOptions(self):
            return SimpleNamespace(graph_optimization_level=None)

        def InferenceSession(self, model_path, **kwargs):
            self.calls.append(kwargs["providers"])
            if kwargs["providers"] == ["OpenVINOExecutionProvider"]:
                raise RuntimeError("provider failed")
            return FakeSession(kwargs["providers"])

    fake_ort = FakeOrt()
    monkeypatch.setattr(detector_module.platform, "processor", lambda: "Intel(R) Core(TM)")
    monkeypatch.setattr(detector_module, "_openvino_is_available", lambda: True)
    monkeypatch.setattr(detector_module, "_require_onnxruntime", lambda **kwargs: fake_ort)
    detector_module.clear_session_cache()

    session = detector_module.get_shared_session("model.onnx", backend="auto")

    assert session.get_providers() == ["CPUExecutionProvider"]
    assert fake_ort.calls == [["OpenVINOExecutionProvider"], ["CPUExecutionProvider"]]


def test_detector_passes_backend_options_to_shared_session(monkeypatch):
    sentinel_session = object()
    captured = {}

    def fake_get_shared_session(model_path, **kwargs):
        captured["model_path"] = model_path
        captured.update(kwargs)
        return sentinel_session

    monkeypatch.setattr(detector_module, "get_shared_session", fake_get_shared_session)
    detector = MLTableDetector(
        model_path="model.onnx",
        backend="openvino",
        provider_options={"device_type": "CPU"},
    )

    assert detector._load_session() is sentinel_session
    assert captured["backend"] == "openvino"
    assert captured["provider_options"] == {"device_type": "CPU"}


def test_warmup_session_runs_dummy_inference():
    called = []

    class DummyInput:
        name = "images"
        shape = [1, 3, 640, 640]

    class FakeSessionWithRun:
        def get_inputs(self):
            return [DummyInput()]

        def run(self, output_names, input_feed):
            called.append((output_names, input_feed))
            return ["dummy_output"]

    fake_sess = FakeSessionWithRun()
    detector_module.warmup_session(fake_sess, input_size=640)

    assert len(called) == 1
    out_names, feed = called[0]
    assert out_names is None
    assert "images" in feed
    assert feed["images"].shape == (1, 3, 640, 640)


def test_detector_warmup_calls_warmup_session(monkeypatch):
    warmed = []
    fake_session = object()

    monkeypatch.setattr(
        detector_module, "get_shared_session", lambda *args, **kwargs: fake_session
    )
    monkeypatch.setattr(
        detector_module,
        "warmup_session",
        lambda sess, input_size: warmed.append((sess, input_size)),
    )

    detector = MLTableDetector(model_path="dummy.onnx", input_size=640)
    detector.warmup()

    assert len(warmed) == 1
    assert warmed[0] == (fake_session, 640)

