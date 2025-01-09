import json
import pathlib

import click
from click import echo
from click_default_group import DefaultGroup

from tilly.utils import get_app_dir
from tilly.plugins import hookimpl

from bs4 import BeautifulSoup
from datetime import timezone
import httpx
import git
import os
import pathlib
from urllib.parse import urlencode
import sqlite_utils
from sqlite_utils.db import NotFoundError
import time
import markdown

from datasette.app import Datasette
import uvicorn
from asgiref.sync import async_to_sync

root = pathlib.Path.cwd()


@hookimpl
def til_command(cli):
    @cli.group(
        cls=DefaultGroup,
        default="build",
        default_if_no_args=True,
    )
    @click.version_option(message="tilly-github, version %(version)s")
    def github():
        """Publish TILs with github."""

    @github.command(name="build")
    def github_build():
        """Build database tils.db."""
        build_database(root)

    @github.command(name="serve")
    def serve():
        """Serve tils.db using datasette."""
        serve_datasette()

    @github.command(name="gen_static")
    def gen_static():
        """Generate static site from tils.db using datasette."""
        urls = ["/", "/cat_a/til_1"]
        get(urls=urls)

    @github.command(name="config")
    @click.option("url", "-u", "--url", help="Base url where posts will be published.")
    def config(url):
        """List config."""
        config_path = config_file()

        config = {"url": url}

        if url:
            with open(config_path, "w") as f:
                json.dump(config, f, indent=4)

        echo(config_path)
        echo(json.dumps(config, indent=4, default=str))


def config_file():
    return get_app_dir() / "github_config.json"


def load_config():
    config_path = config_file()

    if config_path.exists():
        return json.loads(config_path.read_text())
    else:
        return {}


def datasette():
    script_dir = pathlib.Path(__file__).parent
    return Datasette(
        files=["tils.db"],
        static_mounts=[("static", script_dir / "static")],
        plugins_dir=script_dir / "plugins",
        template_dir=script_dir / "templates",
    )


def serve_datasette():
    ds = datasette()

    # Get the ASGI application and serve it
    app = ds.app()
    uvicorn.run(app, host="localhost", port=8001)


@async_to_sync
async def get(urls=None):
    ds = datasette()
    await ds.invoke_startup()

    for url in urls:
        echo(f"GET {url}")
        httpx_response = await ds.client.request(
            "GET",
            url,
            follow_redirects=False,
            avoid_path_rewrites=True,
        )
        echo(httpx_response.text)


def create_html():
    echo("create_html")


def build_database(repo_path):
    echo(f"build_database {repo_path}")
    config = load_config()
    all_times = created_changed_times(repo_path)
    db = sqlite_utils.Database(repo_path / "tils.db")
    table = db.table("til", pk="path")
    for filepath in root.glob("*/*.md"):
        fp = filepath.open()
        title = fp.readline().lstrip("#").strip()
        body = fp.read().strip()
        path = str(filepath.relative_to(root))
        slug = filepath.stem
        url = config.get("url", "") + "{}".format(path)
        # Do we need to render the markdown?
        path_slug = path.replace("/", "_")
        try:
            row = table.get(path_slug)
            previous_body = row["body"]
            previous_html = row["html"]
        except (NotFoundError, KeyError):
            previous_body = None
            previous_html = None
        record = {
            "path": path_slug,
            "slug": slug,
            "topic": path.split("/")[0],
            "title": title,
            "url": url,
            "body": body,
        }
        if (body != previous_body) or not previous_html:

            record["html"] = markdown.markdown(body)
            print("Rendered HTML for {}".format(path))

        # Populate summary
        record["summary"] = first_paragraph_text_only(
            record.get("html") or previous_html or ""
        )
        record.update(all_times[path])
        with db.conn:
            table.upsert(record, alter=True)

    # enable full text search
    table.enable_fts(
        ["title", "body"], tokenize="porter", create_triggers=True, replace=True
    )





def first_paragraph_text_only(html):
    """
    Extracts and returns the text of the first paragraph from a html object.

    Args:
        html: The HTML content.

    Returns:
        str: The text of the first paragraph, or an empty string if not found.
    """
    try:
        soup = BeautifulSoup(html, "html.parser")
        # Attempt to find the first paragraph and extract its text
        first_paragraph = soup.find("p")
        return " ".join(first_paragraph.stripped_strings)
    except AttributeError:
        # Handle the case where 'soup.find('p')' returns None
        return ""


def created_changed_times(repo_path, ref="main"):
    """
    Extract creation and modification timestamps for all files in a git repository.

    Args:
        repo_path (str): Path to the git repository
        ref (str, optional): Git reference (branch, tag, commit). Defaults to "main"

    Returns:
        dict: Dictionary with filepaths as keys and nested dictionaries as values containing:
            - created: Initial commit timestamp in local timezone
            - created_utc: Initial commit timestamp in UTC
            - updated: Latest commit timestamp in local timezone
            - updated_utc: Latest commit timestamp in UTC

    Raises:
        ValueError: If repository has uncommitted changes or untracked files
    """
    # Initialize empty dictionary to store file timestamps
    created_changed_times = {}

    # Open git repository with GitDB backend
    repo = git.Repo(repo_path, odbt=git.GitDB)

    # Ensure working directory is clean before processing
    if repo.is_dirty() or repo.untracked_files:
        raise ValueError("The repository has changes or untracked files.")

    # Get commits in reverse chronological order (oldest first)
    commits = reversed(list(repo.iter_commits(ref)))

    # Process each commit
    for commit in commits:
        dt = commit.committed_datetime
        # Get list of files modified in this commit
        affected_files = list(commit.stats.files.keys())

        # Update timestamps for each affected file
        for filepath in affected_files:
            # If file not seen before, record creation time
            if filepath not in created_changed_times:
                created_changed_times[filepath] = {
                    "created": dt.isoformat(),
                    "created_utc": dt.astimezone(timezone.utc).isoformat(),
                }
            # Always update the modification time
            created_changed_times[filepath].update(
                {
                    "updated": dt.isoformat(),
                    "updated_utc": dt.astimezone(timezone.utc).isoformat(),
                }
            )
    return created_changed_times
