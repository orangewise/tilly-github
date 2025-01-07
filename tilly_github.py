from click import echo
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

root = pathlib.Path.cwd()


@hookimpl
def til_command(cli):
    @cli.command()
    def github():
        """Publish TILs with github."""
        build_database(root)


def first_paragraph_text_only(soup):
    """
    Extracts and returns the text of the first paragraph from a BeautifulSoup object.

    Args:
        soup (BeautifulSoup): A BeautifulSoup object representing the HTML content.

    Returns:
        str: The text of the first paragraph, or an empty string if not found.
    """
    try:
        # Attempt to find the first paragraph and extract its text
        first_paragraph = soup.find('p')
        return ' '.join(first_paragraph.stripped_strings)
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


def build_database(repo_path):
    echo(f"build_database {repo_path}")
    all_times = created_changed_times(repo_path)
    db = sqlite_utils.Database(repo_path / "tils.db")
    table = db.table("til", pk="path")
    for filepath in root.glob("*/*.md"):
        fp = filepath.open()
        title = fp.readline().lstrip("#").strip()
        body = fp.read().strip()
        path = str(filepath.relative_to(root))
        slug = filepath.stem
        url = "https://github.com/simonw/til/blob/main/{}".format(path)
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
            retries = 0
            response = None
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
                    record["html"] = response.text
                    print("Rendered HTML for {}".format(path))
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
        # Populate summary
        record["summary"] = first_paragraph_text_only(
            record.get("html") or previous_html or ""
        )
        record.update(all_times[path])
        with db.conn:
            table.upsert(record, alter=True)

    table.enable_fts(
        ["title", "body"], tokenize="porter", create_triggers=True, replace=True
    )

