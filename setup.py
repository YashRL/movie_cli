from setuptools import setup, find_packages

setup(
    name="moviecli",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "typer>=0.9",
        "rich>=13",
        "ffmpeg-python>=0.2",
    ],
    entry_points={
        "console_scripts": ["mc=moviecli.main:main"],
    },
)
