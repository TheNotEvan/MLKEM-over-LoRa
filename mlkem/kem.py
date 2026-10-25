import  secrets
from .import  kpke
from . import  params
from  .encoding import byte_encode, byte_decode
from .sampling import H, J, G

def key_gen_internal(d, z, params: params):
    epke, dpke = kpke.key_gen(d, params)
    dk = dpke  + epke + H(epke) + z
    return epke, dk

def encaps_internal(ek , m, params: params):
    g = G(m + H(ek))
    K, r = g[:32], g[32:]
    c = kpke.encrypt(ek, m, r, params)
    return K, c

def decaps_internal(dk, c, params: params):
    k = params.k
    dpke = dk[0 : 384 * k]
    epke = dk[384 * k : 768 * k + 32]
    h = dk[768 * k + 32 : 768 * k + 64]
    z = dk[768 * k + 64 : 768 * k + 96]
    mprime = kpke.decrypt(dpke, c, params)
    g = G(mprime + h)
    Kprime, rprime = g[:32], g[32:]
    K = J(z + c)
    cprime = kpke.encrypt(epke, mprime, rprime, params)
    if c != cprime:
        Kprime = K
    return Kprime

def ml_kem_key_gen(params: params):
    d = secrets.token_bytes(32)
    z = secrets.token_bytes(32)
    ek, dk = key_gen_internal(d, z, params)
    return ek, dk


def ml_kem_encaps(ek, params: params):
    m = secrets.token_bytes(32)
    K, c = encaps_internal(ek, m, params)
    return K, c

def ml_kem_decaps(dk, c, params: params):
    Kprime = decaps_internal(dk, c, params)
    return Kprime