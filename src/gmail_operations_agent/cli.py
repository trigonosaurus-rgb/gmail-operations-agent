"""Command line entry point: `gmail-agent auth | run | once | status`."""

import argparse
import asyncio
import contextlib
import json
import logging
import signal
import sys
from datetime import UTC, datetime, timedelta

from gmail_operations_agent.config import Settings
from gmail_operations_agent.errors import BlockedError, ConfigError
from gmail_operations_agent.logging_setup import setup_logging

logger = logging.getLogger("gmail_operations_agent")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="gmail-agent", description="Gmail triage agent with retries and human review."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("auth", help="log in to Google in the browser and save the token")
    commands.add_parser("run", help="process Gmail continuously")
    commands.add_parser("once", help="poll Gmail once, process what is due, and exit")
    commands.add_parser("status", help="print message counts and LLM spend for the last 24 hours")
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to a legacy codepage
    settings = Settings()
    setup_logging(settings.log_level, settings.log_format)

    try:
        if args.command == "auth":
            return _auth(settings)
        if args.command == "status":
            return _status(settings)
        return asyncio.run(_run(settings, once=args.command == "once"))
    except ConfigError as exc:
        logger.error("%s", exc)
        return 2
    except BlockedError as exc:
        logger.error("%s", exc)
        return 3
    except KeyboardInterrupt:
        # Safe at any point: state is persisted around every side effect.
        logger.info("Interrupted")
        return 130


def _auth(settings: Settings) -> int:
    from gmail_operations_agent.integrations.google_auth import login, required_scopes

    login(
        settings.google_credentials_file,
        settings.google_token_file,
        required_scopes(settings.sheets_enabled),
    )
    logger.info("Google login complete")
    return 0


def _status(settings: Settings) -> int:
    from gmail_operations_agent.store import Store

    store = Store(settings.agent_db_path)
    since = datetime.now(UTC) - timedelta(hours=24)
    print(json.dumps(store.stats(since), indent=2, ensure_ascii=False))
    return 0


async def _run(settings: Settings, once: bool) -> int:
    from gmail_operations_agent.runtime import build_gmail_runtime

    problems = settings.problems_for_gmail()
    if problems:
        raise ConfigError(" ".join(problems))
    runtime = build_gmail_runtime(settings)
    try:
        if once:
            await runtime.worker.tick()
            return 0
        stop = asyncio.Event()
        _install_signal_handlers(stop)
        await runtime.worker.run(stop)
        return 0
    finally:
        runtime.store.close()


def _install_signal_handlers(stop: asyncio.Event) -> None:
    """SIGTERM (docker stop) finishes the current cycle and exits cleanly."""
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        # Not supported on Windows, where Ctrl+C raises KeyboardInterrupt instead.
        with contextlib.suppress(NotImplementedError, RuntimeError):
            loop.add_signal_handler(sig, stop.set)


if __name__ == "__main__":
    raise SystemExit(main())
