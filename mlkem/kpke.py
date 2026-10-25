import numpy as np
from .params import n, q
from .ntt import ntt, ntt_inv, poly_add, matrix_vector_ntt, vec_dot_ntt
from .encoding import byte_encode, byte_decode, compress, decompress
from .sampling import G, prf, Sample_NTT, sample_poly_CBD

def key_gen(d, params):
    eta1 = params.eta1
    k = params.k

    digest = G(d + bytes([k]))
    rho, sigma = digest[:32], digest[32:]
    N = 0
    A = np.zeros((k,k,n), dtype=np.int64)
    for i in range(k):
        for j in range(k):
            A[i,j] = Sample_NTT(rho + bytes([j]) + bytes([i]))

    S = np.zeros((k,n), dtype=np.int64)
    E = np.zeros((k,n), dtype=np.int64)
    for i in range(k):
        S[i] = sample_poly_CBD(prf(eta1, sigma, N), eta1)
        N += 1

    for i in range(k):
        E[i] = sample_poly_CBD(prf(eta1, sigma, N), eta1)
        N += 1

    for i in range(k):
        S[i] = ntt(S[i])
        E[i] = ntt(E[i])

    t  = matrix_vector_ntt(A, S, k)
    for i in range(k):
        t[i] = poly_add(t[i], E[i])

    epke = b''.join([byte_encode(t[i], 12) for i in range(k)]) + rho
    dpke = b''.join([byte_encode(S[i], 12) for i in range(k)])

    return epke, dpke

def encrypt(epke, m, r, params):
    N = 0
    k = params.k
    eta1 = params.eta1
    eta2 = params.eta2
    du  = params.du
    dv = params.dv
    t = [np.array(byte_decode(epke[i * 384:(i + 1) * 384], 12), dtype=np.int64)
         for i in range(k)]
    rho = epke[384*k:384*k + 32]
    A = np.zeros((k,k,n), dtype=np.int64)
    y = np.zeros((k,n), dtype=np.int64)
    e1 = np.zeros((k,n), dtype=np.int64)
    for i in range(k):
        for j in range(k):
            A[i,j] = Sample_NTT(rho + bytes([j]) + bytes([i]))

    for i in range(k):
        y[i] = sample_poly_CBD(prf(eta1, r, N), eta1)
        N += 1

    for i in range(k):
        e1[i] = sample_poly_CBD(prf(eta2, r, N), eta2)
        N += 1
    e2 = sample_poly_CBD(prf(eta2, r, N), eta2)

    for i in range(k):
        y[i] = ntt(y[i])

    AT = np.transpose(A, (1,0,2))
    uhat = matrix_vector_ntt(AT, y, k)
    u = np.zeros((k,n), dtype=np.int64)
    for i in range(k):
        u[i] = poly_add(ntt_inv(uhat[i]), e1[i])
    mu = decompress(byte_decode(m, 1), 1)
    v = (ntt_inv(vec_dot_ntt(t, y, k)) + e2 + mu) % q
    c1 = b''.join(byte_encode(compress(u[i], du), du) for i in range(k))
    c2 = byte_encode(compress(v, dv), dv)
    return c1 + c2

def decrypt(dpke, c, params):
    k = params.k
    du = params.du
    dv = params.dv
    
    c1 = c[0: 32 * du * k]
    c2 = c[32 * du * k: 32 * (k * du + dv)]

    u = [decompress(byte_decode(c1[i * 32 * du: (i + 1) * 32 * du], du), du) for i in range(k)]
    v = decompress(byte_decode(c2, dv), dv)
    s = [  byte_decode( dpke[i * 384: (i+1) * 384] , 12)     for i in range (k)]
    uhat = [ntt(u[i]) for i in range(k)] 

    w = (v - ntt_inv(vec_dot_ntt(uhat, s, k)) ) % q
    m = byte_encode(compress(w, 1), 1)

    return m 