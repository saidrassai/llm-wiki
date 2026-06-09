from setuptools import setup, find_packages

setup(
    name="wiki-rag",
    version="1.0.0",
    description="Two-phase pipeline for building a RAG knowledge base from ArXiv papers",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    author="wiki-rag contributors",
    license="MIT",
    packages=find_packages(),
    python_requires=">=3.9",
    install_requires=[
        "pymupdf>=1.25.0",
    ],
    extras_require={
        "openai": ["openai>=1.0"],
        "dev": ["pytest", "black", "ruff"],
    },
    entry_points={
        "console_scripts": [
            "wiki-rag-collect=wiki_rag.collect:main",
            "wiki-rag-ingest=wiki_rag.ingest:main",
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Science/Research",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Topic :: Scientific/Engineering :: Artificial Intelligence",
    ],
)
