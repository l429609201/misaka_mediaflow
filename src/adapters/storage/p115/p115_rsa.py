# src/adapters/storage/p115/p115_rsa.py
#
# 115 proapi RSA 加解密 — 内嵌实现，无外部依赖，兼容 Python 3.11+
#
# 源自: https://github.com/ChenyangGao/p115client/tree/main/modules/p115rsacipher
# 协议: MIT
# 内嵌原因: p115rsacipher 包要求 Python>=3.12，镜像使用 Python 3.11

from __future__ import annotations

from base64 import b64decode, b64encode
from typing import Final

__all__ = ["encrypt", "decrypt"]

G_kts: Final = bytes([
    0xf0,0xe5,0x69,0xae,0xbf,0xdc,0xbf,0x8a,0x1a,0x45,0xe8,0xbe,0x7d,0xa6,0x73,0xb8,
    0xde,0x8f,0xe7,0xc4,0x45,0xda,0x86,0xc4,0x9b,0x64,0x8b,0x14,0x6a,0xb4,0xf1,0xaa,
    0x38,0x01,0x35,0x9e,0x26,0x69,0x2c,0x86,0x00,0x6b,0x4f,0xa5,0x36,0x34,0x62,0xa6,
    0x2a,0x96,0x68,0x18,0xf2,0x4a,0xfd,0xbd,0x6b,0x97,0x8f,0x4d,0x8f,0x89,0x13,0xb7,
    0x6c,0x8e,0x93,0xed,0x0e,0x0d,0x48,0x3e,0xd7,0x2f,0x88,0xd8,0xfe,0xfe,0x7e,0x86,
    0x50,0x95,0x4f,0xd1,0xeb,0x83,0x26,0x34,0xdb,0x66,0x7b,0x9c,0x7e,0x9d,0x7a,0x81,
    0x32,0xea,0xb6,0x33,0xde,0x3a,0xa9,0x59,0x34,0x66,0x3b,0xaa,0xba,0x81,0x60,0x48,
    0xb9,0xd5,0x81,0x9c,0xf8,0x6c,0x84,0x77,0xff,0x54,0x78,0x26,0x5f,0xbe,0xe8,0x1e,
    0x36,0x9f,0x34,0x80,0x5c,0x45,0x2c,0x9b,0x76,0xd5,0x1b,0x8f,0xcc,0xc3,0xb8,0xf5,
])

# 注意：变量名沿用原始库的命名约定（与数学上的 e/n 含义相反）
# RSA_e = 模数 n（大数），RSA_n = 公钥指数 e（65537=0x10001）
# pow 调用: pow(msg, RSA_n, RSA_e) 即 pow(msg, e=0x10001, n=大数)
RSA_e: Final = 0x8686980c0f5a24c4b9d43020cd2c22703ff3f450756529058b1cf88f09b8602136477198a6e2683149659bd122c33592fdb5ad47944ad1ea4d36c6b172aad6338c3bb6ac6227502d010993ac967d1aef00f0c8e038de2e4d3bc2ec368af2e9f10a6f1eda4f7262f136420c07c331b871bf139f74f3010e3c4fe57df3afb71683
RSA_n: Final = 0x10001

to_bytes = int.to_bytes
from_bytes = int.from_bytes


def _acc_step(start: int, stop: int, step: int = 1):
    for i in range(start + step, stop, step):
        yield start, i, step
        start = i
    if start != stop:
        yield start, stop, stop - start


def _bytes_xor(v1: bytes | bytearray | memoryview, v2: bytes | bytearray | memoryview) -> bytes:
    return to_bytes(from_bytes(v1) ^ from_bytes(v2), len(memoryview(v1)))


def _gen_key(rand_key: bytes | bytearray | memoryview, sk_len: int) -> bytearray:
    xor_key = bytearray(sk_len)
    length = sk_len * (sk_len - 1)
    index = 0
    for i in range(sk_len):
        x = (rand_key[i] + G_kts[index]) & 0xff
        xor_key[i] = G_kts[length] ^ x
        length -= sk_len
        index += sk_len
    return xor_key


def _pad_pkcs1_v1_5(message: bytes | bytearray | memoryview) -> int:
    length = len(memoryview(message))
    return from_bytes(b"\x00" + b"\x02" * (126 - length) + b"\x00" + bytes(message))


def _xor(src: bytes | bytearray | memoryview, key: bytes | bytearray | memoryview) -> bytearray:
    src = memoryview(src)
    key = memoryview(key)
    secret = bytearray()
    i = len(src) & 0b11
    if i:
        secret += _bytes_xor(src[:i], key[:i])
    for i, j, s in _acc_step(i, len(src), len(key)):
        secret += _bytes_xor(src[i:j], key[:s])
    return secret


def encrypt(data: str | bytes | bytearray) -> bytes:
    """加密 pick_code 请求体，用于 proapi.115.com/android/2.0/ufile/download"""
    if isinstance(data, str):
        data = data.encode("utf-8")
    xor_text = bytearray(16)
    tmp = memoryview(_xor(data, b"\x8d\xa5\xa5\x8d"))[::-1]
    xor_text += _xor(tmp, b"x\x06\xadL3\x86]\x18L\x01?F")
    cipher_data = bytearray()
    view = memoryview(xor_text)
    for l, r, _ in _acc_step(0, len(view), 117):
        cipher_data += to_bytes(pow(_pad_pkcs1_v1_5(view[l:r]), RSA_n, RSA_e), 128)
    return b64encode(cipher_data)


def decrypt(cipher_data: str | bytes | bytearray) -> bytearray:
    """解密 proapi.115.com 响应中的 data 字段"""
    cipher_data = memoryview(b64decode(cipher_data))
    data = bytearray()
    for l, r, _ in _acc_step(0, len(cipher_data), 128):
        p = pow(from_bytes(cipher_data[l:r]), RSA_n, RSA_e)
        b = to_bytes(p, (p.bit_length() + 0b111) >> 3)
        data += memoryview(b)[b.index(0) + 1:]
    m = memoryview(data)
    key_l = _gen_key(m[:16], 12)
    tmp = memoryview(_xor(m[16:], key_l))[::-1]
    return _xor(tmp, b"\x8d\xa5\xa5\x8d")

