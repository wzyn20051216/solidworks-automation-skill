"""保留 setuptools 安装入口，客户端技能安装由 install.js 管理。"""
from pathlib import Path
import re

from setuptools import setup


ROOT = Path(__file__).resolve().parent
VERSION = re.search(r'(?m)^version\s*=\s*"([^"]+)"', (ROOT / "pyproject.toml").read_text(encoding="utf-8")).group(1)

setup(
    name="solidworks-automation",
    version=VERSION,
    author="wzyn20051216",
    description="Python automation toolkit for SolidWorks API",
    long_description=(ROOT / "README.md").read_text(encoding="utf-8"),
    long_description_content_type="text/markdown",
    url="https://github.com/wzyn20051216/solidworks-automation-skill",
    license="MIT",
    packages=["solidworks_automation"],
    package_dir={"solidworks_automation": "scripts"},
    install_requires=["pywin32>=305; sys_platform == 'win32'", "comtypes>=1.2.0; sys_platform == 'win32'"],
    python_requires=">=3.10",
    classifiers=[
        "Programming Language :: Python :: 3",
        "Operating System :: Microsoft :: Windows",
    ],
    keywords="solidworks automation cad api",
)
