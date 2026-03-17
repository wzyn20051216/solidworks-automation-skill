from setuptools import setup
from setuptools.command.install import install
import os
import shutil
import sys

class PostInstallCommand(install):
    """安装后自动注册到 Claude CLI / Codex"""
    def run(self):
        install.run(self)

        # 获取源目录
        source_dir = os.path.dirname(os.path.abspath(__file__))

        # Claude CLI 路径
        claude_skills_dir = os.path.expanduser("~/.claude/skills/solidworks-automation")

        # Codex 路径（如果存在）
        codex_skills_dir = os.path.expanduser("~/.codex/skills/solidworks-automation")

        # 需要复制的文件和目录
        items_to_copy = ["scripts", "references", "SKILL.md"]

        for target_dir in [claude_skills_dir, codex_skills_dir]:
            try:
                os.makedirs(target_dir, exist_ok=True)
                for item in items_to_copy:
                    src = os.path.join(source_dir, item)
                    dst = os.path.join(target_dir, item)
                    if os.path.isdir(src):
                        if os.path.exists(dst):
                            shutil.rmtree(dst)
                        shutil.copytree(src, dst)
                    elif os.path.isfile(src):
                        shutil.copy2(src, dst)
                print(f"✓ 已安装到: {target_dir}")
            except Exception as e:
                print(f"⚠ 跳过 {target_dir}: {e}", file=sys.stderr)

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="solidworks-automation",
    version="1.0.0",
    author="wzyn20051216",
    description="Python automation toolkit for SolidWorks API",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/wzyn20051216/solidworks-automation-skill",
    packages=["solidworks_automation"],
    package_dir={"solidworks_automation": "scripts"},
    cmdclass={"install": PostInstallCommand},
    install_requires=["pywin32>=305"],
    python_requires=">=3.8",
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: Microsoft :: Windows",
    ],
    keywords="solidworks automation cad api",
)
