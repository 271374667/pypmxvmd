"""Setuptools entry point for building the optional Cython accelerators."""

import os

from setuptools import Extension, find_packages, setup


COMPILER_DIRECTIVES = {
    "language_level": 3,
    "boundscheck": False,
    "wraparound": False,
    "cdivision": True,
    "initializedcheck": False,
    "nonecheck": False,
}


def build_extensions():
    """Return Cython extensions unless a pure-Python build was requested."""
    if os.environ.get("PYPMXVMD_BUILD_CYTHON", "1") == "0":
        return []

    from Cython.Build import cythonize

    extensions = [
        Extension(
            "pypmxvmd.common.io._fast_binary",
            ["pypmxvmd/common/io/_fast_binary.pyx"],
        ),
        Extension(
            "pypmxvmd.common.parsers._fast_vmd",
            ["pypmxvmd/common/parsers/_fast_vmd.pyx"],
        ),
        Extension(
            "pypmxvmd.common.parsers._fast_pmx",
            ["pypmxvmd/common/parsers/_fast_pmx.pyx"],
        ),
    ]

    if os.name == "nt":
        for extension in extensions:
            extension.define_macros = [("_CRT_SECURE_NO_WARNINGS", None)]

    return cythonize(
        extensions,
        compiler_directives=COMPILER_DIRECTIVES,
        annotate=False,
    )


setup(
    packages=find_packages(include=["pypmxvmd", "pypmxvmd.*"]),
    ext_modules=build_extensions(),
    zip_safe=False,
)
