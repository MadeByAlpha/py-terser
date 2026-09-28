"""Cython pure-Python mode kernels: run interpreted unless compiled with `cythonize`."""

import cython


@cython.cfunc
@cython.locals(n=cython.long, i=cython.long)
@cython.returns(cython.bint)
def _is_prime(n):
    if n < 2:
        return False
    i = 2
    while i * i <= n:
        if n % i == 0:
            return False
        i += 1
    return True


@cython.ccall
def primes(limit: cython.long) -> list:
    found: list = []
    n: cython.long
    for n in range(limit):
        if _is_prime(n):
            found.append(n)
    return found


@cython.ccall
@cython.boundscheck(False)
@cython.wraparound(False)
def collatz_length(n: cython.long) -> cython.long:
    steps: cython.long = cython.declare(cython.long, 0)
    while n != 1:
        n = n // 2 if n % 2 == 0 else 3 * n + 1
        steps += 1
    return steps


def describe() -> dict[str, object]:
    return {
        "compiled": cython.compiled,
        "sizeof_long": cython.sizeof(cython.long),
        "typeof": cython.typeof(cython.declare(cython.double, 1.5)),
    }
