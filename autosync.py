import logging
import datetime
import asyncio
from typing import Any, TypedDict
from pathlib import Path
from os import PathLike

import discord
import msgspec
import xxhash


_log: logging.Logger = logging.getLogger(__name__)


class SavedConfig(TypedDict):
    last_timestamp: int
    last_hex: str


class SaveConfig:
    """Represents the config manager for AutoSyncTree.

    Parameters
    ----------
    directory: str | PathLike
        The directory where the config file will be stored. Defaults to the current working directory.
    filename: str
        The name of the config file (without .json extension). Defaults to "discord_py_autosync_config".
    """

    def __init__(
        self,
        directory: str | PathLike,
        filename: str,
    ) -> None:
        self.__directory = Path(directory)
        self.__filename = filename

        self.__path: Path | None = None
        self._config: SavedConfig | None = None
        self.get_config(force_reload=True)

    @property
    def directory(self) -> Path:
        """The directory where the config file is stored."""
        return self.__directory

    @directory.setter
    def directory(self, new_path: str | PathLike) -> None:
        if not isinstance(new_path, (str, PathLike)):
            raise TypeError(f"Expected PathLike, got {type(new_path).__name__}")

        new_path = Path(new_path)
        _log.debug(
            f"[AutoSyncTree] Changing autosync directory from {self.__directory} to {new_path}"
        )
        self.__directory = new_path
        self.__path = None

    @property
    def path(self) -> Path:
        """The full path to the config file."""
        if self.__path:
            return self.__path

        self.__path = self.__directory / f"{self.filename}.json"
        self.__ensure_path_exists(self.__path)
        return self.__path

    @property
    def filename(self) -> str:
        """The name of the config file (without .json extension)."""
        return self.__filename

    @filename.setter
    def filename(self, new_filename: str) -> None:
        if not isinstance(new_filename, str):
            raise TypeError(f"Expected str, got {type(new_filename).__name__}")

        new_filename = new_filename.removesuffix(".json")
        _log.debug(
            f"[AutoSyncTree] Changing autosync filename from {self.__filename} to {new_filename}"
        )
        self.__filename = new_filename
        self.__path = None

    def __ensure_path_exists(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text("{}", encoding="utf-8")

    def get_config(self, force_reload: bool = False) -> SavedConfig:
        """Retrieves the current config."""
        if self._config is not None and not force_reload:
            return self._config

        try:
            content = self.path.read_text(encoding="utf-8")
            self._config = msgspec.json.decode(content, type=SavedConfig)
            _log.info(f"[AutoSyncTree] Loaded config from {self.path}")
        except Exception as e:
            _log.warning(f"[AutoSyncTree] Failed to load config from {self.path}: {e}")
            self._config = {"last_hex": None, "last_timestamp": None}  # type: ignore

        return self._config  # pyright: ignore[reportReturnType]

    def _update(self, new_hex: str) -> None:
        config = self.get_config()
        _log.info(f"[AutoSyncTree] Updating autosync config: New hex: {new_hex}")
        config["last_hex"] = new_hex
        config["last_timestamp"] = int(discord.utils.utcnow().timestamp())
        self.path.write_text(
            msgspec.json.encode(config).decode("utf-8"), encoding="utf-8"
        )
        self._config = config

    @property
    def last_synced_at(self) -> datetime.datetime | None:
        """class:`datetime.datetime` | None: When the last successful sync occurred."""
        timestamp = self.get_config().get("last_timestamp")
        if not timestamp:
            return None
        return datetime.datetime.fromtimestamp(timestamp, tz=datetime.timezone.utc)

    @property
    def last_hex(self) -> str | None:
        """:class:`str` | None: Hex string representing the last synced state."""
        return self.get_config().get("last_hex")


class AutoSyncTree(discord.app_commands.CommandTree):
    """Represents a CommandTree that automatically syncs commands based on hex comparison and time intervals.'

    Parameters
    ----------
    config: SaveConfig | None
        An instance of SaveConfig to manage the sync configuration. If None, a default config will be created.
    minimal_sync_interval: int | float | datetime.timedelta | None
        The minimal interval between syncs. If set to None, there is no minimal interval.
        Defaults to 300 seconds (5 minutes) if not provided.

        You can set the attributes of `config_manager` after initialization to change the config file location.
    """

    DEFAULT_MINIMAL_SYNC_INTERVAL_SECONDS: int = 300  # 5 minutes
    DEFAULT_FILENAME: str = "discord_py_autosync_config"

    def __init__(
        self,
        *args: Any,
        config: SaveConfig | None = None,
        minimal_sync_interval: int
        | float
        | datetime.timedelta
        | None = discord.utils.MISSING,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)

        if config and not isinstance(config, SaveConfig):
            raise TypeError(
                "config must be an instance of SaveConfig or None, not "
                f"{type(config).__name__}"
            )

        self._config_manager: SaveConfig = config or SaveConfig(
            directory=Path.cwd(), filename=self.DEFAULT_FILENAME
        )
        self.minimal_sync_interval: datetime.timedelta | None = None

        if minimal_sync_interval is not None:
            if minimal_sync_interval is discord.utils.MISSING:
                self.minimal_sync_interval = datetime.timedelta(
                    seconds=self.DEFAULT_MINIMAL_SYNC_INTERVAL_SECONDS
                )
            elif isinstance(minimal_sync_interval, datetime.timedelta):
                self.minimal_sync_interval = minimal_sync_interval
            else:
                self.minimal_sync_interval = datetime.timedelta(
                    seconds=float(minimal_sync_interval)
                )

        self._current_hex: str | None = None

    @property
    def config_manager(self) -> SaveConfig:
        """:class:`SaveConfig`: The config manager for autosync settings.

        You can set the `directory` and `filename` attributes of the returned object to change the config file location.
        """
        return self._config_manager

    @property
    def last_synced_at(self) -> datetime.datetime | None:
        """An alias for :attr:`SaveConfig.last_synced_at`."""
        return self.config_manager.last_synced_at

    @property
    def last_hex(self) -> str | None:
        """An alias for :attr:`SaveConfig.last_hex`."""
        return self.config_manager.last_hex

    @property
    def current_hex(self) -> str | None:
        """:class:`str` | None: The current hex string representing the command state."""
        return self._current_hex

    @property
    def can_sync(self) -> bool:
        """:class:`bool`: Whether enough time has passed since the last sync to allow a new sync."""
        last_sync = self.last_synced_at
        minimal_sync_interval = self.minimal_sync_interval
        _log.info(
            f"[AutoSyncTree] Checking whether we can sync... last sync was at {last_sync}, minimal interval is "
            f"{f'set to {minimal_sync_interval.total_seconds()} seconds' if minimal_sync_interval else 'not set'}"
        )
        if self.minimal_sync_interval is None or last_sync is None:
            _log.info(
                "[AutoSyncTree] Can sync: True (no minimal interval or no last sync)"
            )
            return True

        now = discord.utils.utcnow()
        res = (now - last_sync) >= self.minimal_sync_interval
        next_sync = last_sync + self.minimal_sync_interval
        _log.info(
            f"[AutoSyncTree] Current time: {now} {'>=' if res else '<'} Next sync time: {next_sync}, can sync: {res}"
        )
        return res

    async def should_sync(self) -> bool:
        """:class:`bool`: Determines whether a sync is needed based on hex comparison and sync interval."""
        _log.info("[AutoSyncTree] Checking if sync is needed...")
        if not self.can_sync:
            return False

        last_hex = self.last_hex
        current_hex = await self.generate_hex()

        if last_hex and len(last_hex) != len(current_hex):
            _log.warning(
                f"[AutoSyncTree] Hex length mismatch: Last hex length {len(last_hex)} != Current hex length {len(current_hex)}. Messing with the config file? This will force a sync."
            )

        res = last_hex != current_hex
        _log.info(
            f"[AutoSyncTree] Last hex: {last_hex or ''} {'!=' if res else '=='} Current hex: {current_hex}, need to sync: {res}"
        )
        return res

    async def generate_hex(self, guild: discord.abc.Snowflake | None = None) -> str:
        """:class:`str`: Generates a hex string representing the current state of commands."""
        commands = sorted(
            self._get_all_commands(guild=guild), key=lambda c: c.qualified_name
        )
        translator = self.translator
        if translator:
            payload = await asyncio.gather(*[
                c.get_translated_payload(self, translator) for c in commands
            ])
        else:
            payload = [c.to_dict(self) for c in commands]

        self._current_hex = xxhash.xxh64_hexdigest(
            msgspec.msgpack.encode(payload), seed=0
        )
        return self._current_hex

    async def sync(
        self, *, guild: discord.abc.Snowflake | None = None
    ) -> list[discord.app_commands.AppCommand]:
        if not await self.should_sync():
            return []

        synced_commands = await super().sync(guild=guild)

        self.config_manager._update(
            self.current_hex or (await self.generate_hex(guild=guild))
        )
        _log.info(
            f"[AutoSyncTree] Synced {len(synced_commands)} commands {'globally' if guild is None else f'to guild {guild.id}'}."
        )
        return synced_commands
