import numpy as np
from .params import n, q

ZETA = 17

def bitrev7(i):
    return int(format(i, "07b")[::-1], 2)

ZETAS = [pow(ZETA, bitrev7(i), q) for i in range(128)]
GAMMAS = [pow(ZETA, (2 * bitrev7(i)) + 1, q) for i in range(128)]

def poly_add(a, b):
    return (a + b) % q

def ntt(f):
    fhat = np.asarray(f, dtype=np.int64) % q
    i = 1
    length = 128
    while length >= 2:
        for start in range(0, n, 2 * length):
            zeta = ZETAS[i]
            i += 1
            for j in range(start, start + length):
                t = (zeta * fhat[j + length]) % q
                fhat[j + length] = (fhat[j] - t) % q
                fhat[j] = (fhat[j] + t) % q
        length //= 2
    return fhat

def ntt_inv(fhat):
    f = np.asarray(fhat, dtype=np.int64) % q
    i = 127
    length = 2
    while length <= 128:
        for start in range(0, n, 2 * length):
            zeta = ZETAS[i]
            i -= 1
            for j in range(start, start + length):
                t = f[j]
                f[j] = (t + f[j + length]) % q
                f[j + length] = (zeta * (f[j + length] - t)) % q
        length *= 2
    return (f * 3303) % q      

def base_case_multiply(a0, a1, b0, b1, gamma):
    c0 = ((a0 * b0) + (a1 * b1 * gamma)) % q
    c1 = ((a0 * b1) + (a1 * b0)) % q
    return c0, c1

def multiply_ntts(fhat, ghat):
    fhat = np.asarray(fhat, dtype=np.int64)
    ghat = np.asarray(ghat, dtype=np.int64)
    hhat = np.zeros(n, dtype=np.int64)
    for i in range(128):
        hhat[2*i], hhat[(2*i) + 1] = base_case_multiply(fhat[2*i], fhat[(2*i) + 1], ghat[2*i], ghat[(2*i) + 1], GAMMAS[i])
    return hhat

def matrix_vector_ntt(M, v, k):
    out = np.zeros((k,n), dtype=np.int64)
    for i in range(k):
        acc = np.zeros(n, dtype = np.int64)
        for j in range(k):
            acc = poly_add(acc, multiply_ntts(M[i,j], v[j]))
        out[i] = acc
    return out

def vec_dot_ntt(u,v, k):
    acc = np.zeros(n, dtype=np.int64)
    for i in range(k):
        acc = poly_add(acc, multiply_ntts(u[i], v[i]))
    return acc