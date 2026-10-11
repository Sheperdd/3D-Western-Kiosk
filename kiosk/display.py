from pathlib import Path

from aiohttp import web

WEB_DIR = Path(__file__).resolve().parent / "web"

DISPLAY_DATA = web.AppKey("display_data", dict)


# display 1
async def student_display(request: web.Request) -> web.Response:
    """Serve the student display page."""
    payload = request.app[DISPLAY_DATA][1]
    return web.json_response(payload, headers={"Cache-Control": "no-store"})


# display 2
async def general_display(request: web.Request) -> web.Response:
    """Serve the general display page."""
    payload = request.app[DISPLAY_DATA][2]
    return web.json_response(payload, headers={"Cache-Control": "no-store"})


async def index(request: web.Request) -> web.FileResponse:
    """Serve the index page."""
    return web.FileResponse(WEB_DIR / "index.html")


async def JavaScriptResponse(request: web.Request) -> web.FileResponse:
    """Serve a JSON response for testing."""
    return web.FileResponse(WEB_DIR / "app.js")


def create_app() -> web.Application:
    """Create the aiohttp web application."""
    app = web.Application()

    app[DISPLAY_DATA] = {
        1: {"screen": "STARTING", "labels": []},
        2: {"screen": "GENERAL INSTRUCTIONS", "labels": ["STARTING"]},
    }

    app.router.add_get("/api/display/1", student_display)
    app.router.add_get("/api/display/2", general_display)
    app.router.add_get("/", index)
    app.router.add_get("/app.js", JavaScriptResponse)
    return app


if __name__ == "__main__":
    web.run_app(create_app(), host="127.0.0.1", port=8000)
