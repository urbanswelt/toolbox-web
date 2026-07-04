"""Top-level page routes: the single-page UI and the favicon."""

from flask import Blueprint, Response, render_template

bp = Blueprint("views", __name__)

# Brand mark (terminal prompt on the accent blue) served as the favicon, so the
# tab shows an icon and /favicon.ico no longer 404s.
FAVICON_SVG = (
    "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'>"
    "<rect width='24' height='24' rx='5' fill='#4c8dff'/>"
    "<path d='M7 8l3.5 4L7 16M13 16h4' fill='none' stroke='#fff' "
    "stroke-width='2' stroke-linecap='round' stroke-linejoin='round'/></svg>"
)


@bp.route("/")
def index():
    return render_template("index.html")


@bp.route("/favicon.svg")
@bp.route("/favicon.ico")
def favicon():
    return Response(
        FAVICON_SVG,
        mimetype="image/svg+xml",
        headers={"Cache-Control": "public, max-age=86400"},
    )
