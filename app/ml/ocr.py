import importlib
from typing import TYPE_CHECKING

import numpy as np

from app.core.errors import ServiceUnavailableError

if TYPE_CHECKING:
    from PIL.Image import Image

OCR_NOT_INSTALLED = "OCR is not installed; run `uv sync --group ocr`"


class RapidOcrEngine:
    def __init__(self) -> None:
        try:
            rapidocr = importlib.import_module("rapidocr")
        except ImportError as error:
            raise ServiceUnavailableError(OCR_NOT_INSTALLED) from error
        self._engine = rapidocr.RapidOCR()

    def read(self, image: "Image") -> list[str]:
        result = self._engine(np.asarray(image.convert("RGB")))
        return [str(line) for line in (result.txts or ())]
