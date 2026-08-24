from setuptools import setup, find_packages
import os

NAME = "hexai_pdf_parser"
VERSION = os.getenv("VER", "1.0.10")

setup(
    name=NAME,
    version=os.getenv("CI_PUBLISH_VER", VERSION),
    description="A Python library for parsing PDF layouts into structured JSON and Markdown",
    author="HexAI Team",
    author_email="junhong.pan@hexinfo.cn",
    python_requires=">=3.7",
    install_requires=[
        "PyMuPDF",
    ],
    extras_require={
        "ml": [
            "onnxruntime>=1.8.0",
            "numpy>=1.20.0",
            "opencv-python>=4.2.0",
        ],
        "demo": [
            "camelot-py[cv]>=0.11.0",
        ],
        "dev": [
            "pytest>=7.0",
        ],
    },
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    package_data={
        "hexai_pdf_parser": ["data/models/*.onnx", "table_templates/*.json"],
    },
    entry_points={
        "console_scripts": [
            "hexai_pdf_parser=hexai_pdf_parser.cli:main",
        ],
    },
)
