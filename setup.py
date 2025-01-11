import setuptools

with open("README.md", "r") as fh:
    long_description = fh.read()

with open('requirements.txt', 'r') as f:
    requirements = [line.strip().split('#')[0] for line in f.read().split('\n') if line.strip().split('#')[0]]

setuptools.setup(
    name="tilly-github",
    version="0.0.1",
    author="Ronald Luitwieler",
    author_email="ronald.luitwieler@gmail.com",
    description="Tilly plugin for publishing with Github",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/tilly-pub/tilly-github",
    packages=setuptools.find_packages(),
    py_modules=["tilly_github"],
    install_requires=requirements,
    entry_points={
        "tilly": ["github = tilly_github"],
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.9",
)