"""MangaFire VRF token generation for authenticated AJAX requests."""

from __future__ import annotations

import base64
from urllib.parse import quote

_RC4_KEYS = [
    "FgxyJUQDPUGSzwbAq/ToWn4/e8jYzvabE+dLMb1XU1o=",
    "CQx3CLwswJAnM1VxOqX+y+f3eUns03ulxv8Z+0gUyik=",
    "fAS+otFLkKsKAJzu3yU+rGOlbbFVq+u+LaS6+s1eCJs=",
    "Oy45fQVK9kq9019+VysXVlz1F9S1YwYKgXyzGlZrijo=",
    "aoDIdXezm2l3HrcnQdkPJTDT8+W6mcl2/02ewBHfPzg=",
]
_SEEDS32 = [
    "yH6MXnMEcDVWO/9a6P9W92BAh1eRLVFxFlWTHUqQ474=",
    "RK7y4dZ0azs9Uqz+bbFB46Bx2K9EHg74ndxknY9uknA=",
    "rqr9HeTQOg8TlFiIGZpJaxcvAaKHwMwrkqojJCpcvoc=",
    "/4GPpmZXYpn5RpkP7FC/dt8SXz7W30nUZTe8wb+3xmU=",
    "wsSGSBXKWA9q1oDJpjtJddVxH+evCfL5SO9HZnUDFU8=",
]
_PREFIX_KEYS = ["l9PavRg=", "Ml2v7ag1Jg==", "i/Va0UxrbMo=", "WFjKAHGEkQM=", "5Rr27rWd"]

_SCHEDULES = [
    [
        lambda c: (c - 223 + 256) & 0xFF,
        lambda c: ((c >> 4) | (c << 4)) & 0xFF,
        lambda c: ((c >> 4) | (c << 4)) & 0xFF,
        lambda c: (c + 234) & 0xFF,
        lambda c: ((c >> 7) | (c << 1)) & 0xFF,
        lambda c: ((c >> 2) | (c << 6)) & 0xFF,
        lambda c: ((c >> 7) | (c << 1)) & 0xFF,
        lambda c: (c - 223 + 256) & 0xFF,
        lambda c: ((c >> 7) | (c << 1)) & 0xFF,
        lambda c: ((c >> 6) | (c << 2)) & 0xFF,
    ],
    [
        lambda c: (c + 19) & 0xFF,
        lambda c: ((c >> 7) | (c << 1)) & 0xFF,
        lambda c: (c + 19) & 0xFF,
        lambda c: ((c >> 6) | (c << 2)) & 0xFF,
        lambda c: (c + 19) & 0xFF,
        lambda c: ((c >> 1) | (c << 7)) & 0xFF,
        lambda c: (c + 19) & 0xFF,
        lambda c: ((c >> 6) | (c << 2)) & 0xFF,
        lambda c: ((c >> 7) | (c << 1)) & 0xFF,
        lambda c: ((c >> 4) | (c << 4)) & 0xFF,
    ],
    [
        lambda c: (c - 223 + 256) & 0xFF,
        lambda c: ((c >> 1) | (c << 7)) & 0xFF,
        lambda c: (c + 19) & 0xFF,
        lambda c: (c - 223 + 256) & 0xFF,
        lambda c: ((c << 2) | (c >> 6)) & 0xFF,
        lambda c: (c - 223 + 256) & 0xFF,
        lambda c: (c + 19) & 0xFF,
        lambda c: ((c << 1) | (c >> 7)) & 0xFF,
        lambda c: ((c << 2) | (c >> 6)) & 0xFF,
        lambda c: ((c << 1) | (c >> 7)) & 0xFF,
    ],
    [
        lambda c: (c + 19) & 0xFF,
        lambda c: ((c << 1) | (c >> 7)) & 0xFF,
        lambda c: ((c << 1) | (c >> 7)) & 0xFF,
        lambda c: ((c >> 1) | (c << 7)) & 0xFF,
        lambda c: (c + 234) & 0xFF,
        lambda c: ((c << 1) | (c >> 7)) & 0xFF,
        lambda c: (c - 223 + 256) & 0xFF,
        lambda c: ((c << 6) | (c >> 2)) & 0xFF,
        lambda c: ((c << 4) | (c >> 4)) & 0xFF,
        lambda c: ((c << 1) | (c >> 7)) & 0xFF,
    ],
    [
        lambda c: ((c >> 1) | (c << 7)) & 0xFF,
        lambda c: ((c << 1) | (c >> 7)) & 0xFF,
        lambda c: ((c << 6) | (c >> 2)) & 0xFF,
        lambda c: ((c >> 1) | (c << 7)) & 0xFF,
        lambda c: ((c << 2) | (c >> 6)) & 0xFF,
        lambda c: ((c >> 4) | (c << 4)) & 0xFF,
        lambda c: ((c << 1) | (c >> 7)) & 0xFF,
        lambda c: ((c << 1) | (c >> 7)) & 0xFF,
        lambda c: (c - 223 + 256) & 0xFF,
        lambda c: ((c << 2) | (c >> 6)) & 0xFF,
    ],
]


def _to_bytes(value: str) -> list[int]:
    return [ord(char) & 0xFF for char in value]


def _from_bytes(values: list[int]) -> str:
    return "".join(chr(value & 0xFF) for value in values)


def _b64encode(data: str) -> str:
    return base64.b64decode(data).decode("latin1")


def _b64decode_std(value: str) -> str:
    return base64.b64encode(value.encode("latin1")).decode("ascii")


def _rc4_bytes(key: str, values: list[int]) -> list[int]:
    state = list(range(256))
    swap = 0
    for position in range(256):
        swap = (swap + state[position] + ord(key[position % len(key)])) & 0xFF
        state[position], state[swap] = state[swap], state[position]

    output: list[int] = []
    index = 0
    swap = 0
    for value in values:
        index = (index + 1) & 0xFF
        swap = (swap + state[index]) & 0xFF
        state[index], state[swap] = state[swap], state[index]
        key_byte = state[(state[index] + state[swap]) & 0xFF]
        output.append(((value or 0) ^ key_byte) & 0xFF)
    return output


def _transform(
    values: list[int],
    init_seed: list[int],
    prefix_key: list[int],
    prefix_len: int,
    schedule: list,
) -> list[int]:
    output: list[int] = []
    for index, value in enumerate(values):
        if index < prefix_len:
            output.append(prefix_key[index] if index < len(prefix_key) else 0)
        operation = schedule[index % 10]
        if operation:
            seed = init_seed[index % 32] if init_seed else 0
            output.append(operation(((value or 0) ^ seed) & 0xFF) & 0xFF)
    return output


def _bytes_from_base64(value: str) -> list[int]:
    return _to_bytes(_b64encode(value))


def _base64_url_encode_bytes(values: list[int]) -> str:
    encoded = _b64decode_std(_from_bytes(values))
    return encoded.replace("+", "-").replace("/", "_").rstrip("=")


def mangafire_id_part(slug: str) -> str:
    slug = slug.strip()
    if "." in slug:
        return slug.rsplit(".", 1)[-1]
    return slug


def generate_vrf(value: str) -> str:
    values = _to_bytes(quote(value, safe=""))
    for step in range(5):
        values = _rc4_bytes(_b64encode(_RC4_KEYS[step]), values)
        prefix_key = _bytes_from_base64(_PREFIX_KEYS[step])
        values = _transform(
            values,
            _bytes_from_base64(_SEEDS32[step]),
            prefix_key,
            len(prefix_key),
            _SCHEDULES[step],
        )
    return _base64_url_encode_bytes(values)
