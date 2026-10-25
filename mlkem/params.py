from dataclasses import dataclass

n = 256
q = 3329


@dataclass(frozen=True)
class Params:
    name: str
    k: int
    eta1: int
    eta2: int
    du: int
    dv: int

    @property
    def ek_bytes(self) -> int:
        return 384 * self.k + 32

    @property
    def dk_bytes(self) -> int:
        return 384 * self.k + self.ek_bytes + 64

    @property
    def ct_bytes(self) -> int:
        return 32 * (self.du * self.k + self.dv)

    @property
    def ss_bytes(self) -> int:
        return 32

ML_KEM_512 = Params(
    name="ML-KEM-512",
    k=2,
    eta1=3,
    eta2=2,
    du=10,
    dv=4
)

ML_KEM_768 = Params(
    name="ML-KEM-768",
    k=3,
    eta1=2,
    eta2=2,
    du=10,
    dv=4
)

ML_KEM_1024 = Params(
    name="ML-KEM-1024",
    k=4,
    eta1=2,
    eta2=2,
    du=11,
    dv=5
)

