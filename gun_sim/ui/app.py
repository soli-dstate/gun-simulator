"""Desktop app: the UI in its own native window.

pywebview hosts the HTML UI in the system web engine (Edge WebView2 on
Windows), which gives us WebGL for the 3D view. The page calls Python directly
through window.pywebview.api (the Bridge below); there is no browser and no
server the user has to know about.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from . import api


class Bridge:
    """Methods callable from the page as window.pywebview.api.<name>(...).

    Errors are returned as {"error": message} so the page can show them.
    Attributes starting with _ are not exposed to JavaScript.
    """

    def __init__(self):
        self._window = None

    def _call(self, fn, *args):
        try:
            return fn(*args)
        except Exception as e:
            return {"error": api.error_message(e)}

    def schema(self):
        return self._call(api.schema)

    def simulate(self, payload):
        return self._call(api.simulate, payload)

    def synthesize(self, payload):
        return self._call(api.synthesize, payload)

    def trajectory(self, payload):
        return self._call(api.trajectory, payload)

    def parse(self, text):
        return self._call(api.parse_toml, text)

    def save_toml(self, text, filename):
        """Ask where to save, then write the file. Returns {"path": ...} or {"path": None} if cancelled."""
        import webview

        def save():
            chosen = self._window.create_file_dialog(
                webview.FileDialog.SAVE, save_filename=filename, file_types=("TOML files (*.toml)", "All files (*.*)")
            )
            if isinstance(chosen, (list, tuple)):
                chosen = chosen[0] if chosen else None
            if not chosen:
                return {"path": None}
            Path(chosen).write_text(text, encoding="utf-8")
            return {"path": str(chosen)}

        return self._call(save)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="gun_sim.ui", description="Open the gun simulator.")
    parser.add_argument("--browser", action="store_true", help="serve the UI to a web browser instead of a window")
    parser.add_argument("--port", type=int, default=0, help="with --browser: port to listen on")
    parser.add_argument("--debug", action="store_true", help="enable the web inspector (right-click > Inspect)")
    args = parser.parse_args(argv)

    if args.browser:
        from .server import serve

        serve(args.port)
        return

    import webview

    bridge = Bridge()
    bridge._window = webview.create_window(
        "Gun Simulator",
        url=str(api.STATIC_DIR / "index.html"),
        js_api=bridge,
        width=1440,
        height=920,
        min_size=(900, 600),
    )
    webview.start(debug=args.debug)


if __name__ == "__main__":
    main()
