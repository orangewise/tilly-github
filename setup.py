from setuptools import setup

with open('requirements.txt', 'r') as f:
    requirements = [line.strip().split('#')[0] for line in f.read().split('\n') if line.strip().split('#')[0]]

setup(
    name="tilly-github",
    version="0.0.1",
    url="https://github.com/tilly-pub/tilly-github",
    py_modules=["tilly_github"],
    install_requires=requirements,
    entry_points={
        "tilly": ["github = tilly_github"],
    },
)