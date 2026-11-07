from pathlib import Path

from setuptools import setup
from setuptools.command.install import install


class PostInstallCommand(install):
    """保留 setuptools 兼容入口，不触碰用户已有的 Skill 目录。"""

    def run(self):
        install.run(self)
        print("Use `node install.js --help` or an MCPB release to install the Skill/MCP runtime.")


ROOT = Path(__file__).resolve().parent
long_description = (ROOT / "README.md").read_text(encoding="utf-8")

setup(
    name="solidworks-automation",
    version="2.1.0",
    author="wzyn20051216",
    description="Python automation toolkit for SolidWorks API",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/wzyn20051216/solidworks-automation-skill",
    license="MIT",
    packages=["solidworks_automation"],
    package_dir={"solidworks_automation": "scripts"},
    cmdclass={"install": PostInstallCommand},
    install_requires=["pywin32>=305", "comtypes>=1.2.0"],
    python_requires=">=3.10",
    classifiers=[
        "Programming Language :: Python :: 3",
        "Operating System :: Microsoft :: Windows",
    ],
    keywords="solidworks automation cad api",
)
