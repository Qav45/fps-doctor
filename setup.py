from setuptools import setup, find_packages

with open("README.md", encoding="utf-8") as f:
    long_description = f.read()

setup(
    name="fps-doctor",
    version="1.1.0",
    description="Windows PC FPS & performance diagnostic tool",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Qav45",
    url="https://github.com/Qav45/fps-doctor",
    python_requires=">=3.9",
    install_requires=[
        "psutil>=5.9",
        "WMI>=1.5",
        "GPUtil>=1.4",
        "rich>=13.0",
        "pywin32>=305",
    ],
    packages=find_packages(),
    entry_points={
        "console_scripts": [
            "fps-doctor=main:main",
        ],
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "Operating System :: Microsoft :: Windows",
        "Topic :: System :: Hardware",
        "Environment :: Console",
    ],
)
