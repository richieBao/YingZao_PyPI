# -*- coding: utf-8 -*-
from pathlib import Path
from re import MULTILINE, search

from setuptools import find_packages, setup


ROOT = Path(__file__).parent
README = ROOT / "README.md"
PACKAGE_INIT = ROOT / "src" / "yingzao" / "__init__.py"

version_match = search(
    r'^__version__\s*=\s*"([^"]+)"',
    PACKAGE_INIT.read_text(encoding="utf-8"),
    flags=MULTILINE,
)
if version_match is None:
    raise RuntimeError("Unable to determine package version.")


setup(
    name="yingzao",
    version=version_match.group(1),
    license="MIT",
    author="Richie Bao-(coding-x.tech)",
    author_email="richiebao@outlook.com",
    description="为 Grasshopper 参数化设计模组 yingzao 的支持工具",
    long_description=README.read_text(encoding="utf-8"),
    long_description_content_type="text/markdown",
    url="https://coding-x.tech/",
    package_dir={"": "src"},
    packages=find_packages(where="src"),
    python_requires=">=3.8",
    platforms="any",
)
