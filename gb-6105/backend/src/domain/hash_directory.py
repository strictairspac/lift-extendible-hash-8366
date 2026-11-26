from dataclasses import dataclass, field
from hashlib import sha256

from .certificates import Certificate

MAX_DEPTH = 12


def stable_hash(key):
    return int.from_bytes(sha256(key.encode("ascii")).digest()[:8], "big")


@dataclass
class Bucket:
    number: int
    depth: int
    records: dict[str, Certificate] = field(default_factory=dict)


class Directory:
    def __init__(self, capacity):
        self.capacity = capacity
        self.depth = 0
        self.slots = [Bucket(0, 0)]
        self.splits = 0

    def _bucket(self, key):
        mask = (1 << self.depth) - 1
        return self.slots[stable_hash(key) & mask]

    def _split(self, full):
        if full.depth == self.depth:
            self.slots = self.slots + self.slots
            self.depth += 1
        distinguishing_bit = 1 << full.depth
        full.depth += 1
        sibling = Bucket(full.number | distinguishing_bit, full.depth)
        for slot, candidate in enumerate(self.slots):
            if candidate is full and slot & distinguishing_bit:
                self.slots[slot] = sibling
        for key, record in list(full.records.items()):
            if stable_hash(key) & distinguishing_bit:
                sibling.records[key] = record
                del full.records[key]
        self.splits += 1

    def add(self, record):
        bucket = self._bucket(record.code)
        if record.code in bucket.records:
            raise ValueError(f"证书编号重复 {record.code}")
        while len(bucket.records) >= self.capacity and bucket.depth < MAX_DEPTH:
            self._split(bucket)
            bucket = self._bucket(record.code)
        bucket.records[record.code] = record

    def locate(self, key):
        bucket = self._bucket(key)
        return bucket, bucket.records.get(key)

    def buckets(self):
        unique = {bucket.number: bucket for bucket in self.slots}
        return sorted(unique.values(), key=lambda bucket: bucket.number)
