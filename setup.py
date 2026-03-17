from setuptools import setup, find_packages

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
    packages=find_packages(),
    package_dir={"": "scripts"},
    classifiers=[
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "License :: OSI Approved :: MIT License",
        "Operating System :: Microsoft :: Windows",
        "Topic :: Software Development :: Libraries :: Python Modules",
    ],
    python_requires=">=3.8",
    install_requires=[
        "pywin32>=305",
    ],
    keywords="solidworks automation cad api python",
)
