"""Entry point for `panel serve web/app_entry.py` and for the static site build."""

from pegtrace.app import create_app

app = create_app()
if __name__.startswith("bokeh"):  # `panel serve`; the static page renders `app` itself
    app.servable(title="PegTrace")
