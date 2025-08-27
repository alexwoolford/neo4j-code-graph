from __future__ import annotations

from src.utils.batching import get_database_batch_size, run_in_batches
from src.utils.progress import progress_iter, progress_range


def test_get_database_batch_size_rules():
    assert get_database_batch_size(has_embeddings=True) == 250
    assert get_database_batch_size(has_embeddings=False, estimated_size_mb=2) == 500
    assert get_database_batch_size() == 1000


class _SessionRecorder:
    def __init__(self):
        self.calls: list[tuple[str, list[int]]] = []

    def run(self, query: str, **params):  # type: ignore[no-untyped-def]
        self.calls.append((query, list(params.values())[0]))


def test_run_in_batches_executes_expected_slices():
    session = _SessionRecorder()
    data = list(range(10))
    run_in_batches(session, "UNWIND $items AS x RETURN x", data, batch_size=4, param_key="items")
    # Expect 3 batches: [0..3], [4..7], [8..9]
    assert [vals for _, vals in session.calls] == [list(range(4)), list(range(4, 8)), [8, 9]]


def test_progress_iter_respects_disable_flag():
    data = list(range(5))
    out = list(progress_iter(data, total=len(data), desc="x", disable=True))
    assert out == data


def test_progress_range_computes_total_without_errors():
    # Should iterate correctly independent of tqdm availability
    out = list(progress_range(0, 5, step=2))
    assert out == [0, 2, 4]
