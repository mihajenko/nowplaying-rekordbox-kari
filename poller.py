import asyncio
import base64
import datetime as dt
import functools
import logging
import os
from asyncio import CancelledError
from functools import partial
from pathlib import Path

import click
from pydantic import BaseModel
from pynput import keyboard
from pyrekordbox import Rekordbox6Database
from pyrekordbox.db6 import DjmdArtist, DjmdContent, DjmdSongHistory
from sqlalchemy.orm import Session
from websockets import ConnectionClosedOK, ServerConnection
from websockets.asyncio.server import serve

# Set constants
os.putenv("WEBSOCKETS_MAX_LINE_LENGTH", "81920")
os.putenv("WEBSOCKETS_MAX_BODY_SIZE", "10_485_760")
os.putenv("LOGLEVEL", "INFO")

logging.basicConfig(
    level=logging.getLevelNamesMapping()[os.getenv("LOGLEVEL", "INFO")],
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# SongInfo polling
class SongInfo(BaseModel):
    artist: str | None = None
    title: str | None = None
    album: str | None = None
    artwork: str | None = None


class RekordboxPoller:
    def __init__(self) -> None:
        self.db = Rekordbox6Database()
        self.share_dir = self.get_share_dir()
        self._history = None

    @staticmethod
    def get_share_dir() -> Path:
        # Windows: %APPDATA%\Pioneer\rekordbox\share
        app_data = os.getenv("APPDATA")
        if app_data:
            share = Path(app_data) / "Pioneer" / "rekordbox" / "share"
            if share.is_dir():
                return share

        raise FileNotFoundError("Could not locate Rekordbox share directory")

    def _load_image_as_base64_data_uri(self, relative_path: str) -> str | None:
        full_path = self.share_dir / relative_path.lstrip("/")
        if not full_path.is_file():
            return None

        try:
            image_data = full_path.read_bytes()
        except OSError as e:
            logger.warning("Failed to read artwork file %s: %s", full_path, e)
            return None

        # Encode
        b64 = base64.b64encode(image_data).decode("ascii")

        # Guess MIME type from extension
        match full_path.suffix.lower():
            case ".jpg" | ".jpeg":
                mimetype = "image/jpeg"
            case ".png":
                mimetype = "image/png"
            case _:
                mimetype = "image/*"

        return f"data:{mimetype};base64,{b64}"  # noqa:

    @functools.lru_cache(maxsize=100)
    def poll(self, _cache_key: str) -> SongInfo | None:
        session: Session = self.db.session
        try:
            history = (
                session.query(DjmdSongHistory)
                .join(DjmdContent, DjmdSongHistory.ContentID == DjmdContent.ID)
                .outerjoin(DjmdArtist, DjmdContent.ArtistID == DjmdArtist.ID)
                .where(DjmdContent.Title is not None)
                .order_by(DjmdSongHistory.created_at.desc())
                .limit(1)
                .all()
            )
        except Exception as e:
            logger.error("Database query failed: %s", e)
            return SongInfo()

        # Compare if any changes from the last history
        if history:
            if self._history == history:
                logger.debug("Has history data, SAME as before.")
                return None
            else:
                logger.debug("Has history data, DIFFERENT than before.")
                self._history = history
        else:
            logger.debug("No track history found.")
            return None

        # Get the last song info.
        content = history[-1].Content
        artwork_data_uri = (
            self._load_image_as_base64_data_uri(content.ImagePath)
            if content.ImagePath
            else None
        )

        return SongInfo(
            artist=getattr(content.Artist, "Name", None),
            title=content.Title,
            album=getattr(content.Album, "Name", None),
            artwork=artwork_data_uri,
        )


# Rekordbox database poller
poller = RekordboxPoller()


async def _send_track_info(websocket: ServerConnection):
    cache_key = dt.datetime.now(tz=dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    state = poller.poll(cache_key)
    if state is not None:
        logger.debug("Sending message ...")
        try:
            await websocket.send(state.model_dump_json())
        except ConnectionClosedOK:
            logger.debug("Connection cleanup finalized.")


def setup_keyboard_listening() -> tuple[keyboard.Listener, asyncio.Queue]:
    """
    Start a keyboard listener that will send the hotkey event as a queue item.

    Note: F8 is being listened for.

    Returns:
        The keyboard listener and the `asyncio.Queue` instance
    """
    queue = asyncio.Queue()
    loop = asyncio.get_event_loop()

    def on_activate():
        nonlocal queue
        logger.debug(f"Hotkey {keyboard.Key.f8!r} pressed.")
        loop.call_soon_threadsafe(queue.put_nowait, True)

    hotkey = keyboard.HotKey(
        [  # type: ignore
            keyboard.Key.f8,
        ],
        on_activate,
    )
    return keyboard.Listener(on_press=hotkey.press, on_release=hotkey.release), queue


async def wait_for_hotkey(
    websocket: ServerConnection,
    key_queue: asyncio.Queue,
):
    """
    Waits for a hotkey event before sending track information to the websocket.

    Args:
        websocket: ServerConnection
        key_queue: Queue to listen to
    """
    while True:
        key = await key_queue.get()
        if key:
            await _send_track_info(websocket)


async def wait_for_interval(
    websocket: ServerConnection,
    interval: float = 3.0,
):
    """
    Waits for an interval (in seconds) before sending track information to the
    websocket.

    Args:
        websocket: ServerConnection
        interval: Seconds to wait until polling for new track information.
    """
    while True:
        await _send_track_info(websocket)
        await asyncio.sleep(interval)


async def main(host: str, port: int, interval: float, hotkey_mode: bool):
    # Keyboard Listener
    if hotkey_mode:
        kb_listener, key_queue = setup_keyboard_listening()
        ws_handler = partial(wait_for_hotkey, key_queue=key_queue)
        kb_listener.start()
    else:
        kb_listener = None
        ws_handler = partial(wait_for_interval, interval=interval)

    # WebSocket server
    async with serve(ws_handler, host=host, port=port) as server:
        await server.serve_forever()

    if kb_listener is not None:
        kb_listener.join()


# CLI part
@click.command()
@click.option(
    "--host",
    default="127.0.0.1",
    help="Hostname to bind the server to.",
    type=str,
)
@click.option(
    "--port",
    default=8080,
    help="Port to bind the server to.",
    type=int,
)
@click.option(
    "--interval",
    default=3.0,
    help="Polling interval in seconds.",
    type=float,
)
@click.option(
    "--hotkey-mode",
    default=False,
    help="Enable hotkey (F8) to load the latest track info. "
    "Disables polling on an interval.",
    type=bool,
)
def cli(host: str, port: int, interval: float, hotkey_mode: bool):
    try:
        asyncio.run(main(host, port, interval, hotkey_mode))
    except CancelledError:
        logger.warning("Ending program.")


if __name__ == "__main__":
    cli()
