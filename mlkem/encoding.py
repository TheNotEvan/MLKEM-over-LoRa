from .params import n, q

def compress(poly,d):
    return [(((x << d) + (q//2)) // q) % (1 << d) for x in poly]

def decompress(poly , d):
    return [(((q * y) + (1 << (d-1))) >> d)  for y in poly]

def bits_to_bytes(bits, length):
    B = [0] * length
    for i in range(8 * length):
        B[i//8] = B[i//8] + bits[i] * (2 ** (i % 8))
    return bytes(B)

def bytes_to_bits(B, length):
    C = list(B)
    b = [0] * (length  * 8)
    for i in range(length):
        for j in range(8):
            b[(8 * i) + j] = C[i] % 2
            C[i] = (C[i] // 2)
    return b

def byte_encode(poly, d):
    m = q if d == 12 else 2 ** d
    assert all(0 <= x < m for x in poly)
    b = [0] * (256 * d)
    for i in range(n):
        a = poly[i]
        for j in range(d):
            b[(i * d) + j] = a % 2 
            a = (a-b[(i*d) + j]) // 2
    B = bits_to_bytes(b, 32 * d)
    return B

def byte_decode(B, d):
    b = bytes_to_bits(B, d * 32)
    m = q if d == 12 else 2 ** d
    F = [0] * 256
    for i in range(n):
        val = 0
        for j in range(d):
            val += b[(i * d) + j] * (2 ** j)
        F[i] = val % m
    return F