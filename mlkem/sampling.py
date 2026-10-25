import hashlib
from .params import n, q
from .encoding import bytes_to_bits

class XOF:
    def __init__ (self):
        self._ctx = hashlib.shake_128()
        self._pos = 0
        self._buf = b''

    def absorb(self, data: bytes):
        self._ctx.update(data)
        self._pos = 0
        self._buf = b''
        return self

    def squeeze(self, num_bytes: int) -> bytes:
        end = self._pos + num_bytes
        if end > len(self._buf):
            new_len = max(end, len(self._buf) * 2, 512)
            self._buf = self._ctx.digest(new_len)
        out = self._buf[self._pos:end]
        self._pos = end
        return out


def H (s):
    return hashlib.sha3_256(s).digest()

def J (s):
    return hashlib.shake_256(s).digest(32)

def G (c):
    return hashlib.sha3_512(c).digest()

def prf(eta, s, b):
    return hashlib.shake_256(s + bytes([b])).digest(64 * eta)

def Sample_NTT(B):
    j = 0
    a = [0] * n 
    xof = XOF()
    xof.absorb(B)
    while j < n:
        C = xof.squeeze(3)
        d1 = C[0] + (256 * (C[1] % 16))
        d2 = (C[1]//16) + (16 * C[2])
        if d1 < q:
            a[j] = d1
            j += 1
        if d2 < q and j < n:
            a[j] = d2
            j += 1
    return a

def sample_poly_CBD(B, eta):
    b = bytes_to_bits(B, len(B))
    f = [0] * n
    for i in range(n):
        x, y = 0,0
        for j in range(eta):
            x += b[(2 * i * eta) + j]
            y += b[(2 * i * eta) + eta + j]
        f[i] = (x - y) % q
    return f


