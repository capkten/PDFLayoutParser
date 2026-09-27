from setuptools import setup, find_packages
import os

NAME = "hexai_pdf_parser"
VERSION = os.getenv("VER", "1.1.4")

setup(
    name=NAME,
    version=os.getenv("CI_PUBLISH_VER", VERSION),
    description="A Python library for parsing PDF layouts into structured JSON and Markdown",
    author="HexAI Team",
    author_email="junhong.pan@hexinfo.cn",
    python_requires=">=3.7",
    install_requires=[
        "PyMuPDF",
        "typing_extensions>=3.7.4; python_version<'3.8'",
    ],
    extras_require={
        "ml": [
            "onnxruntime>=1.8.0",
            "numpy>=1.20.0",
            "opencv-python>=4.2.0",
        ],
        "ml-openvino": [
            "onnxruntime-openvino==1.24.1; python_version >= '3.10'",
            "openvino==2025.4.1; python_version >= '3.10'",
            "numpy>=1.20.0",
            "opencv-python>=4.2.0",
        ],
        "dev": [
            "pytest>=7.0",
        ],
    },
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    package_data={
        "hexai_pdf_parser.tables": ["table_templates/*.json"],
        "hexai_pdf_parser.ml": ["table_detector_model/*.onnx"],
    },
    entry_points={
        "console_scripts": [
            "hexai_pdf_parser=hexai_pdf_parser.core.cli:main",
        ],
    },
)
