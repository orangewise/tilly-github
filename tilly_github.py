import pathlib

import click
from click import echo
from click_default_group import DefaultGroup

from tilly.plugin import hookimpl


root = pathlib.Path.cwd()

@hookimpl
def til_command(cli):
    @cli.group(
        cls=DefaultGroup,
        default="default",
        default_if_no_args=True,
    )
    @click.version_option(message="tilly-github, version %(version)s")
    def github():
        """Publish TILs with github."""

    @github.command("default")
    def default():
        echo("<implement a default action>")













