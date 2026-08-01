from functools import lru_cache

import tiktoken


@lru_cache(maxsize=1)
def get_encoder() -> tiktoken.Encoding:
    return tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    if not text:
        return 0
    encoder = get_encoder()
    return len(encoder.encode(text))


def truncate_to_tokens(text: str, max_tokens: int) -> str:
    encoder = get_encoder()
    tokens = encoder.encode(text)
    if len(tokens) <= max_tokens:
        return text
    return encoder.decode(tokens[:max_tokens])
