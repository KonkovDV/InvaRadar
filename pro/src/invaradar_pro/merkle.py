"""Журнал прозрачности: дерево Меркла по RFC 9162 (Certificate Transparency v2).

Цепочка хешей (events.py) ловит любую правку, но, чтобы доказать одно событие, её нужно
показать целиком. Дерево Меркла даёт два коротких доказательства размером O(log n):

- **включения**: событие № i входит в журнал с корнем R (подрядчику — его приёмка, жителю — его сообщение);
- **согласованности**: журнал размера m — префикс журнала размера n (вчерашний подписанный корень
  не переписан задним числом).

Хеширование по RFC 9162 §2.1.1: лист — SHA-256(0x00 ‖ данные), узел — SHA-256(0x01 ‖ левый ‖ правый);
дерево делится по наибольшей степени двойки, меньшей n. Голову дерева (размер, корень, время)
подписывает оператор: здесь — HMAC для демо, в промышленной версии — УКЭП по ГОСТ Р 34.10-2012.
"""
from __future__ import annotations

import hashlib
import hmac

EMPTY_ROOT = hashlib.sha256(b"").digest()


def leaf_hash(data: bytes) -> bytes:
    return hashlib.sha256(b"\x00" + data).digest()


def node_hash(left: bytes, right: bytes) -> bytes:
    return hashlib.sha256(b"\x01" + left + right).digest()


def _split(n: int) -> int:
    """Наибольшая степень двойки, строго меньшая n (n ≥ 2)."""
    k = 1
    while k << 1 < n:
        k <<= 1
    return k


class MerkleTree:
    def __init__(self, leaves: list[bytes] | None = None):
        self._leaves: list[bytes] = []
        self._memo: dict[tuple[int, int], bytes] = {}
        for x in leaves or []:
            self.append(x)

    def append(self, data: bytes) -> int:
        self._leaves.append(leaf_hash(data))
        self._memo.clear()
        return len(self._leaves) - 1

    def __len__(self) -> int:
        return len(self._leaves)

    def _mth(self, lo: int, hi: int) -> bytes:
        # A dict on the instance, cleared on append. functools.cache would keep the tree alive.
        key = (lo, hi)
        hit = self._memo.get(key)
        if hit is not None:
            return hit
        n = hi - lo
        if n == 0:
            out = EMPTY_ROOT
        elif n == 1:
            out = self._leaves[lo]
        else:
            k = _split(n)
            out = node_hash(self._mth(lo, lo + k), self._mth(lo + k, hi))
        self._memo[key] = out
        return out

    def root(self, size: int | None = None) -> bytes:
        size = len(self._leaves) if size is None else size
        if not 0 <= size <= len(self._leaves):
            raise ValueError("размер вне журнала")
        return self._mth(0, size)

    def inclusion_proof(self, index: int, size: int | None = None) -> list[bytes]:
        size = len(self._leaves) if size is None else size
        if not 0 <= index < size <= len(self._leaves):
            raise ValueError("индекс вне дерева")

        def path(m: int, lo: int, hi: int) -> list[bytes]:
            n = hi - lo
            if n == 1:
                return []
            k = _split(n)
            if m < k:
                return path(m, lo, lo + k) + [self._mth(lo + k, hi)]
            return path(m - k, lo + k, hi) + [self._mth(lo, lo + k)]

        return path(index, 0, size)

    def consistency_proof(self, old_size: int, new_size: int | None = None) -> list[bytes]:
        new_size = len(self._leaves) if new_size is None else new_size
        if not 0 < old_size <= new_size <= len(self._leaves):
            raise ValueError("размеры вне журнала")
        if old_size == new_size:
            return []

        def sub(m: int, lo: int, hi: int, b: bool) -> list[bytes]:
            n = hi - lo
            if m == n:
                return [] if b else [self._mth(lo, hi)]
            k = _split(n)
            if m <= k:
                return sub(m, lo, lo + k, b) + [self._mth(lo + k, hi)]
            return sub(m - k, lo + k, hi, False) + [self._mth(lo, lo + k)]

        return sub(old_size, 0, new_size, True)


def verify_inclusion(leaf: bytes, index: int, size: int, proof: list[bytes], root: bytes) -> bool:
    """RFC 9162 §2.1.3.2. leaf — уже хеш листа (leaf_hash(данные))."""
    if index >= size:
        return False
    fn, sn, r = index, size - 1, leaf
    for p in proof:
        if sn == 0:
            return False
        if fn & 1 or fn == sn:
            r = node_hash(p, r)
            if not fn & 1:
                while not (fn & 1) and fn != 0:
                    fn >>= 1
                    sn >>= 1
        else:
            r = node_hash(r, p)
        fn >>= 1
        sn >>= 1
    return sn == 0 and r == root


def verify_consistency(old_size: int, new_size: int, old_root: bytes, new_root: bytes, proof: list[bytes]) -> bool:
    """RFC 9162 §2.1.4.2."""
    if old_size == new_size:
        return not proof and old_root == new_root
    if old_size == 0 or old_size > new_size or not proof:
        return False
    path = list(proof)
    if old_size & (old_size - 1) == 0:
        path = [old_root] + path
    fn, sn = old_size - 1, new_size - 1
    while fn & 1:
        fn >>= 1
        sn >>= 1
    fr = sr = path[0]
    for c in path[1:]:
        if sn == 0:
            return False
        if fn & 1 or fn == sn:
            fr = node_hash(c, fr)
            sr = node_hash(c, sr)
            if not fn & 1:
                while not (fn & 1) and fn != 0:
                    fn >>= 1
                    sn >>= 1
        else:
            sr = node_hash(sr, c)
        fn >>= 1
        sn >>= 1
    return fr == old_root and sr == new_root and sn == 0


def signed_tree_head(tree: MerkleTree, key: bytes, timestamp: str) -> dict:
    """Подписанная голова дерева. HMAC — заглушка для демо; в промышленной версии — УКЭП (ГОСТ Р 34.10-2012)."""
    size, root = len(tree), tree.root().hex()
    msg = f"{size}|{root}|{timestamp}".encode()
    return {"tree_size": size, "root": root, "timestamp": timestamp,
            "signature": hmac.new(key, msg, hashlib.sha256).hexdigest(), "alg": "HMAC-SHA256 (демо)"}


def verify_tree_head(sth: dict, key: bytes) -> bool:
    msg = f"{sth['tree_size']}|{sth['root']}|{sth['timestamp']}".encode()
    return hmac.compare_digest(hmac.new(key, msg, hashlib.sha256).hexdigest(), sth["signature"])
