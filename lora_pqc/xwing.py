from __future__ import annotations

import hashlib
import secrets

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey

from mlkem import kem
from mlkem.params import ML_KEM_768

SK_LEN = 32
PK_LEN = 1216
CT_LEN = 1120
SS_LEN = 32
LABEL = b"\\.//^\\"

def expand(seed):
    expanded =  hashlib.shake_256(seed).digest(96)
    d, z = expanded[:32], expanded[32:64]
    mlkem_pub_key, mlkem_priv_key = kem.key_gen_internal(d, z, ML_KEM_768)
    x25519_private_key = expanded[64:]
    x25519_pub_key = X25519PrivateKey.from_private_bytes(x25519_private_key).public_key().public_bytes_raw()
    return mlkem_pub_key, mlkem_priv_key, x25519_pub_key, x25519_private_key

def generate_key_pair_derand(seed: bytes) -> tuple[bytes, bytes]:
   mlkem_pub_key, mlkem_priv_key, x25519_pub_key, x25519_private_key = expand(seed)
   return seed, mlkem_pub_key + x25519_pub_key


def combine(ss_M, ss_X, ct_X, pk_X):
    return hashlib.sha3_256(ss_M + ss_X + ct_X + pk_X + LABEL).digest()


def encapsulate_derand(pk: bytes, eseed: bytes) -> tuple[bytes, bytes]:
    ml_kem_pub = pk[0:1184]
    x25519_pub = pk[1184:1216]
    x25519_secret = X25519PrivateKey.from_private_bytes(eseed[32:64])
    ct_X = x25519_secret.public_key().public_bytes_raw()
    ss_X = x25519_secret.exchange(X25519PublicKey.from_public_bytes(x25519_pub))
    ss_M, ct_M = kem.encaps_internal(ml_kem_pub, eseed[0:32], ML_KEM_768)
    ss = combine(ss_M, ss_X, ct_X, x25519_pub)
    return ss, ct_M + ct_X

def generate_key_pair() -> tuple[bytes, bytes]:
    seed = secrets.token_bytes(32)
    return generate_key_pair_derand(seed)

def encapsulate(pk: bytes) -> tuple[bytes, bytes]:
    eseed = secrets.token_bytes(64)
    return encapsulate_derand(pk, eseed)


def decapsulate(ct: bytes, sk: bytes) -> bytes:
    _, ml_kem_priv_key, x25519_pub_key, x25519_private_key = expand(sk)
    ct_M = ct[0:1088]
    ct_x = ct[1088:1120]
    ss_M = kem.decaps_internal(ml_kem_priv_key, ct_M, ML_KEM_768)
    x25519_secret = X25519PrivateKey.from_private_bytes(x25519_private_key)
    ss_X = x25519_secret.exchange(X25519PublicKey.from_public_bytes(ct_x))
    ss = combine(ss_M, ss_X, ct_x, x25519_pub_key)
    return ss

