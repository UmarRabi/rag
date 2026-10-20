from pathlib import Path
from typing import Self

from huggingface_hub import hf_hub_download
from tokenizers import Tokenizer

TOKENIZER_FILE = "tokenizer.json"


class HuggingFaceTokenCounter:
    def __init__(self, tokenizer: Tokenizer) -> None:
        self._tokenizer = tokenizer

    @classmethod
    def from_pretrained(cls, model_name: str, cache_dir: Path) -> Self:
        path = hf_hub_download(model_name, TOKENIZER_FILE, cache_dir=cache_dir)
        return cls(Tokenizer.from_file(path))

    def count(self, text: str) -> int:
        return len(self._tokenizer.encode(text, add_special_tokens=False).ids)
