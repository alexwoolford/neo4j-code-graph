import sys
from pathlib import Path
from types import SimpleNamespace

# Ensure src is on the Python path before importing PipelineManager
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

sys.modules.setdefault("dotenv", SimpleNamespace(load_dotenv=lambda **k: None))

from src.pipeline.manager import PipelineManager


def test_has_nvd_api_key(monkeypatch):
    monkeypatch.setattr("dotenv.load_dotenv", lambda override=True: None)
    monkeypatch.delenv("NVD_API_KEY", raising=False)

    manager = PipelineManager("https://example.com/repo.git")

    assert manager._has_nvd_api_key() is False

    monkeypatch.setenv("NVD_API_KEY", "secret")
    assert manager._has_nvd_api_key() is True
