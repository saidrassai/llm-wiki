from setuptools import setup, find_packages

with open("README.md", "r") as f:
    long_description = f.read()

setup(
    name="wiki-rag",
    version="1.0.0",
    description="Two-phase pipeline for building a RAG knowledge base from ArXiv papers",
    long_description=long_description,
    long_description_content_type="text/markdown",
    packages=find_packages(),
    python_requires=">=3.9",
    install_requires=[
        "pymupdf>=1.25.0",
    ],
    extras_require={
        "cron": ["croniter>=2.0.0"],
        "openai": ["openai>=1.0"],
        "all": ["croniter>=2.0.0", "openai>=1.0"],
    },
    entry_points={
        "console_scripts": [
            "wiki-rag-collect=wiki_rag.collect:main",
        ],
    },
)
