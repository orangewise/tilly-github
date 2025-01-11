import json
import pathlib
import shutil

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

    # options shared by multiple commands
    template_dir_option = click.option(
        '--template-dir',
        type=click.Path(exists=True, file_okay=False, dir_okay=True),
        help='Override the default template directory.')

    @github.command(name="build")
    def github_build():
        """Build database tils.db."""
        build_database(root)

    @github.command(name="serve")
    @template_dir_option
    def serve(template_dir):
        """Serve tils.db using datasette."""
        serve_datasette(template_dir)

    @github.command(name="gen-static")
    @template_dir_option
    def gen_static(template_dir):
        """Generate static site from tils.db using datasette."""
        db = database(root)
        urls = ['/'] + [f'/{row["topic"]}/{row["slug"]}' for row in db.query("SELECT topic, slug FROM til")]

        pages = get(urls=urls, template_dir=template_dir)
        write_html(pages)

    @github.command(name="copy-templates")
    def copy():
        """Copy default templates to current repo for customization."""
        copy_templates()

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


def copy_templates(template_dir="templates"):
    script_dir = pathlib.Path(__file__).parent
    src = script_dir / "templates"
    dst = root

    try:
        # Ensure the destination directory exists
        if not os.path.exists(dst):
            os.makedirs(dst)

        shutil.copytree(src, os.path.join(dst, os.path.basename(src)), dirs_exist_ok=True)
        print(f"Successfully copied default templates to {dst}")
    except Exception as e:
        print(f"An error occurred: {e}")
        raise

def config_file():
    return get_app_dir() / "github_config.json"


def load_config():
    config_path = config_file()

    if config_path.exists():
        return json.loads(config_path.read_text())
    else:
        return {}


def datasette(template_dir=None):
    script_dir = pathlib.Path(__file__).parent

    template_dir = template_dir or script_dir / "templates"

    return Datasette(
        files=["tils.db"],
        static_mounts=[("static", script_dir / "static")],
        plugins_dir=script_dir / "plugins",
        template_dir=template_dir,
    )


def serve_datasette(template_dir=None):
    ds = datasette(template_dir=template_dir)

    # Get the ASGI application and serve it
    app = ds.app()
    uvicorn.run(app, host="localhost", port=8001)


@async_to_sync
async def get(urls=None, template_dir=None):
    ds = datasette(template_dir)
    await ds.invoke_startup()

    pages = []
    for url in urls:
        httpx_response = await ds.client.request(
            "GET",
            url,
            follow_redirects=False,
            avoid_path_rewrites=True,
        )
        pages.append({"url": url, "html": httpx_response.text})

    return pages

def write_html(pages):
    static_root = root / "_static"
    echo(f"write_html to {static_root}")

    # clear the directory
    if static_root.exists():
        shutil.rmtree(static_root / "_static", ignore_errors=True)

    for page in pages:
        path = static_root / page["url"].lstrip("/") / "index.html"
        echo(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(page["html"])


def database(repo_path):
    return sqlite_utils.Database(repo_path / "tils.db")


def build_database(repo_path):
    echo(f"build_database {repo_path}")
    config = load_config()
    all_times = created_changed_times(repo_path)
    db = database(repo_path)
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

            record["html"] = github_markdown(body, path)
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

def github_markdown(body, path):
    retries = 0
    response = None
    html = None
    while retries < 3:
        headers = {}
        if os.environ.get("MARKDOWN_GITHUB_TOKEN"):
            headers = {
                "authorization": "Bearer {}".format(
                    os.environ["MARKDOWN_GITHUB_TOKEN"]
                )
            }
        response = httpx.post(
            "https://api.github.com/markdown",
            json={
                # mode=gfm would expand #13 issue links and suchlike
                "mode": "markdown",
                "text": body,
            },
            headers=headers,
        )
        if response.status_code == 200:
            html = response.text
            break
        elif response.status_code == 401:
            assert False, "401 Unauthorized error rendering markdown"
        else:
            print(response.status_code, response.headers)
            print("  sleeping 60s")
            time.sleep(60)
            retries += 1
    else:
        assert False, "Could not render {} - last response was {}".format(
            path, response.headers
        )
    return html




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
