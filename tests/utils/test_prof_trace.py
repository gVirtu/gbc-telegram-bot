import cProfile
import importlib


def test_start_returns_none_when_disabled(monkeypatch):
    monkeypatch.delenv("PROFILE", raising=False)
    import src.utils.prof_trace as pt
    importlib.reload(pt)
    assert pt.start() is None


def test_start_returns_profiler_when_enabled(monkeypatch):
    monkeypatch.setenv("PROFILE", "1")
    import src.utils.prof_trace as pt
    importlib.reload(pt)
    profiler = pt.start()
    assert isinstance(profiler, cProfile.Profile)
    profiler.disable()


def test_stop_noop_with_none():
    import src.utils.prof_trace as pt
    pt.stop(None, "test_label")  # should not raise


def test_stop_writes_prof_file(tmp_path, monkeypatch):
    monkeypatch.setenv("PROFILE", "1")
    monkeypatch.setenv("PROFILE_DIR", str(tmp_path))
    import src.utils.prof_trace as pt
    importlib.reload(pt)
    profiler = pt.start()
    assert profiler is not None
    profiler.disable()
    pt.stop(profiler, "test_batch")
    prof_files = list(tmp_path.glob("test_batch_*.prof"))
    assert len(prof_files) == 1
