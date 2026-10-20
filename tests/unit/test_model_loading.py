import threading
import time
from concurrent.futures import ThreadPoolExecutor

from app.core.settings import Settings
from app.ml.provider import LocalModels

THREADS = 8


def test_models_load_once_even_when_requested_concurrently() -> None:
    models = LocalModels(Settings())
    loads = 0
    counting = threading.Lock()

    def slow_load() -> object:
        nonlocal loads
        with counting:
            loads += 1
        time.sleep(0.05)
        return object()

    with ThreadPoolExecutor(THREADS) as pool:
        loaded = list(pool.map(lambda _: models._once("captioner", slow_load), range(THREADS)))

    assert loads == 1
    assert all(model is loaded[0] for model in loaded)
