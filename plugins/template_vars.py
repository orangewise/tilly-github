import os
import re
import html

from datasette import hookimpl
from bs4 import BeautifulSoup as Soup

non_alphanumeric = re.compile(r"[^a-zA-Z0-9\s]")
multi_spaces = re.compile(r"\s+")


def first_paragraph(html):
    soup = Soup(html, "html.parser")
    return str(soup.find("p"))


def highlight(s):
    s = html.escape(s)
    s = s.replace("b4de2a49c8", "<strong>").replace("8c94a2ed4b", "</strong>")
    return s


@hookimpl
def extra_template_vars(request, datasette):
    async def related_tils(til):
        path = til["path"]
        sql = """
        select
          til.topic, til.slug, til.title, til.created
        from til
          join similarities on til.path = similarities.other_id
        where similarities.id = :path
        order by similarities.score desc limit 10
        """
        result = await datasette.get_database().execute(
            sql,
            {"path": til["path"]},
        )
        return result.rows

    # this is called when this is set in a template: {% set results = search_results(q) %}
    async def search_results(q):
        sql = """
        select * from til
        where rowid in
        (select rowid from til_fts where til_fts match escape_fts(:q)) order by path limit 101
        """
        # where rowid in (select rowid from til where til match escape_fts(:q))

        result = await datasette.get_database().execute(
            sql,
            {"q": q},
        )
        return result.rows

    return {
        "q": request.args.get("q", ""),
        "highlight": highlight,
        "first_paragraph": first_paragraph,
        "related_tils": related_tils,
        "search_results": search_results
    }


@hookimpl
def prepare_connection(conn):
    conn.create_function("first_paragraph", 1, first_paragraph)

@hookimpl
def prepare_jinja2_environment(env):
    if os.environ.get("TILLY_ENABLE_SEARCH", "True") == "True":
        env.globals['enable_search'] = True
    else:
        env.globals['enable_search'] = False

    # tilly config to env.globals
    tilly_config_vars = {k: v for k,v in os.environ.items() if k.startswith("TILLY_")}
    env.globals = {**env.globals, **tilly_config_vars}

