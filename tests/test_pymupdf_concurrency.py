"""Tests for PyMuPDF concurrency protection and non-native parallel execution."""

import threading
import time
from unittest.mock import MagicMock

import pytest
from hexai_pdf_parser.core.models import Document, Page
from hexai_pdf_parser.core.pipeline import Pipeline


def test_cross_instance_native_access_must_be_mutually_exclusive(tmp_path):
    """Two independent Pipeline instances (simulating concurrent web requests)

    must never execute PyMuPDF native operations simultaneously.
    """
    active_native_calls = 0
    max_concurrent_native_calls = 0
    state_lock = threading.Lock()

    def instrumented_normalize(*args, **kwargs):
        nonlocal active_native_calls, max_concurrent_native_calls
        with state_lock:
            active_native_calls += 1
            if active_native_calls > max_concurrent_native_calls:
                max_concurrent_native_calls = active_native_calls
        time.sleep(0.05)  # Simulate native work
        with state_lock:
            active_native_calls -= 1

    doc1 = Document(file_name="doc1.pdf", page_count=1, pages=[Page(index=0, size={"width": 100, "height": 100}, rotation=0, page_type="vector")])
    doc2 = Document(file_name="doc2.pdf", page_count=1, pages=[Page(index=0, size={"width": 100, "height": 100}, rotation=0, page_type="vector")])

    pipe1 = Pipeline(pdf_path="dummy1.pdf")
    pipe2 = Pipeline(pdf_path="dummy2.pdf")

    fake_fitz_doc = MagicMock()
    fake_page = MagicMock()
    fake_page.rotation = 0
    fake_page.clean_contents.side_effect = instrumented_normalize
    fake_page.get_text.return_value = {"blocks": []}
    fake_fitz_doc.__getitem__.return_value = fake_page

    errors = []

    def run_worker(pipeline, doc):
        try:
            pipeline._process_single_page(
                page_index=0,
                document=doc,
                images_dir=str(tmp_path),
                pages_dir=str(tmp_path),
                text_alignment_debug_dir=str(tmp_path),
                pdf_doc=fake_fitz_doc,
                table_extractor=MagicMock(),
            )
        except Exception as e:
            errors.append(e)

    t1 = threading.Thread(target=run_worker, args=(pipe1, doc1))
    t2 = threading.Thread(target=run_worker, args=(pipe2, doc2))

    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert not errors
    # With global sync, max_concurrent_native_calls MUST be strictly 1.
    assert max_concurrent_native_calls == 1, (
        f"Detected race condition: {max_concurrent_native_calls} threads executed "
        "native PyMuPDF operations concurrently across separate Pipeline instances!"
    )


def test_unlocked_computation_runs_concurrently_without_blocking_other_threads(tmp_path):
    """When one thread is executing a long pure-Python computation (e.g. table extraction),

    another thread should be able to enter and finish its native snapshotting without being blocked.
    """
    pipe1 = Pipeline(pdf_path="dummy1.pdf")
    pipe2 = Pipeline(pdf_path="dummy2.pdf")

    doc1 = Document(file_name="doc1.pdf", page_count=1, pages=[Page(index=0, size={"width": 100, "height": 100}, rotation=0, page_type="vector")])
    doc2 = Document(file_name="doc2.pdf", page_count=1, pages=[Page(index=0, size={"width": 100, "height": 100}, rotation=0, page_type="vector")])

    fake_fitz_doc = MagicMock()
    fake_page = MagicMock()
    fake_page.rotation = 0
    fake_page.get_text.return_value = {"blocks": []}
    fake_fitz_doc.__getitem__.return_value = fake_page

    t1_in_computation = threading.Event()
    t2_finished_native = threading.Event()

    def mock_table_extract_t1(*args, **kwargs):
        t1_in_computation.set()
        # Wait until thread 2 has finished its native operation before finishing
        if not t2_finished_native.wait(timeout=2.0):
            raise TimeoutError("Thread 2 was blocked by Thread 1 holding the lock during computation!")
        return []

    mock_extractor_t1 = MagicMock()
    mock_extractor_t1.extract.side_effect = mock_table_extract_t1

    def run_worker1():
        pipe1._process_single_page(
            page_index=0,
            document=doc1,
            images_dir=str(tmp_path),
            pages_dir=str(tmp_path),
            text_alignment_debug_dir=str(tmp_path),
            pdf_doc=fake_fitz_doc,
            table_extractor=mock_extractor_t1,
        )

    def run_worker2():
        # Wait for thread 1 to reach computation phase
        assert t1_in_computation.wait(timeout=2.0)
        # Thread 2 now runs its native page processing
        pipe2._process_single_page(
            page_index=0,
            document=doc2,
            images_dir=str(tmp_path),
            pages_dir=str(tmp_path),
            text_alignment_debug_dir=str(tmp_path),
            pdf_doc=fake_fitz_doc,
            table_extractor=MagicMock(),
        )
        t2_finished_native.set()

    t1 = threading.Thread(target=run_worker1)
    t2 = threading.Thread(target=run_worker2)

    t1.start()
    t2.start()

    t2.join(timeout=3.0)
    assert not t2.is_alive(), "Thread 2 deadlocked or blocked waiting for Thread 1 to finish computation!"
    t1.join(timeout=3.0)
    assert not t1.is_alive()


def test_reentrancy_and_exception_release():
    """Verify that pymupdf_lock is an RLock (re-entrant without deadlocking)

    and releases properly even when an exception is raised.
    """
    from hexai_pdf_parser.core.pymupdf_sync import pymupdf_lock

    # 1. Test reentrancy
    with pymupdf_lock:
        with pymupdf_lock:
            assert True, "Reentrant acquisition failed"

    # 2. Test exception release
    try:
        with pymupdf_lock:
            raise ValueError("boom")
    except ValueError:
        pass

    # Ensure lock can be acquired immediately by another thread
    acquired = threading.Event()

    def try_acquire():
        with pymupdf_lock:
            acquired.set()

    t = threading.Thread(target=try_acquire)
    t.start()
    t.join(timeout=1.0)
    assert acquired.is_set(), "Lock was not released after exception!"
