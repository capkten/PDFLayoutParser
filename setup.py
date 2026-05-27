from setuptools import setup, find_packages
import os

NAME = "hexai_pdf_parser"
VERSION = os.getenv("VER", "0.1.0")

setup(
    name=NAME,
    version=os.getenv("CI_PUBLISH_VER", VERSION),
    description="A Python library for parsing PDF layouts into structured JSON and Markdown",
    author="HexAI Team",
    author_email="support@hexai.com",
    python_requires=">=3.10",
    install_requires=[
        "PyMuPDF>=1.23.0",
    ],
    extras_require={
        "ml": [
            "onnxruntime>=1.16.0",
            "numpy>=1.24.0",
            "opencv-python>=4.8.0",
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
        "hexai_pdf_parser": ["data/models/*.onnx"],
    },
    entry_points={
        "console_scripts": [
            "hexai_pdf_parser=hexai_pdf_parser.cli:main",
        ],
    },
)
