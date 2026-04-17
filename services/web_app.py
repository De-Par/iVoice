from __future__ import annotations

import argparse
import sys
from pathlib import Path


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ivoice-web",
        description="Run the iVoice Streamlit web interface.",
    )
    parser.add_argument(
        "--server-address",
        default=None,
        help="Optional Streamlit server address override.",
    )
    parser.add_argument(
        "--server-port",
        type=int,
        default=None,
        help="Optional Streamlit server port override.",
    )
    return parser


def run() -> None:
    parser = build_argument_parser()
    args = parser.parse_args()

    try:
        from streamlit.web.cli import main as streamlit_main
    except ImportError as error:  # pragma: no cover - optional runtime dependency
        raise RuntimeError(
            "Streamlit is not installed. Install project dependencies first."
        ) from error

    app_path = Path(__file__).resolve().parent.parent / "app" / "web_ui" / "main.py"
    argv = ["streamlit", "run", str(app_path)]
    if args.server_address:
        argv.extend(["--server.address", args.server_address])
    if args.server_port is not None:
        argv.extend(["--server.port", str(args.server_port)])

    sys.argv = argv
    raise SystemExit(streamlit_main())


if __name__ == "__main__":
    run()
