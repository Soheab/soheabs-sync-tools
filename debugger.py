from __future__ import annotations
from typing import TYPE_CHECKING, Any, Protocol
from collections.abc import Callable, Coroutine

import json

import discord
from discord import app_commands
from discord.ext import commands

if TYPE_CHECKING:
    from typing import Protocol

    class OriginalSyncCallable(Protocol):
        async def __call__(
            self, *, guild: discord.abc.Snowflake | None
        ) -> list[app_commands.AppCommand]: ...

else:
    OriginalSyncCallable = Callable[
        ...,
        Coroutine[Any, Any, list[app_commands.AppCommand]],
    ]


CommandT = (
    app_commands.AppCommand
    | app_commands.Command
    | app_commands.Group
    | app_commands.ContextMenu
)


def format_bool_none(value: bool | None) -> str:
    return ("No", "Yes")[value] if value is not None else "Unset"


class _DebugableCommand:
    def __init__(
        self,
        command: CommandT,
        *,
        is_guild_installable: bool,
        is_user_installable: bool,
        is_guild_usable: bool,
        is_dm_usable: bool,
        is_private_channel_usable: bool,
    ) -> None:
        self.command: CommandT = command
        self.is_guild_installable: bool = is_guild_installable
        self.is_user_installable: bool = is_user_installable
        self.is_guild_usable: bool = is_guild_usable
        self.is_dm_usable: bool = is_dm_usable
        self.is_private_channel_usable: bool = is_private_channel_usable

    def __str__(self) -> str:
        return (
            f"- Command '{self.command.name}':\n"
            f"  Can be added to a server: {format_bool_none(self.is_guild_installable)}\n"
            f"  Can be added to a user: {format_bool_none(self.is_user_installable)}\n"
            f"  Can be used in a server: {format_bool_none(self.is_guild_usable)}\n"
            f"  Can be used in the bot's DM: {format_bool_none(self.is_dm_usable)}\n"
            f"  Can be used in an user's or group DM: {format_bool_none(self.is_private_channel_usable)}\n"
        )


class SoheabsTreeDebugger:
    """Class to debug command tree installability and usability issues.

    Parameters
    ----------
    tree: :class:`discord.app_commands.CommandTree`
        The command tree to debug.
    """

    def __init__(
        self,
        tree: discord.app_commands.CommandTree[commands.Bot],
    ) -> None:
        if not isinstance(tree, discord.app_commands.CommandTree):
            raise TypeError(
                "tree must be an instance of discord.app_commands.CommandTree"
            )

        self.__original_tree_sync: OriginalSyncCallable = tree.sync
        tree.sync = self.new_sync  # type: ignore
        self.tree: app_commands.CommandTree[commands.Bot] = tree

        self._global_allowed_contexts: app_commands.AppCommandContext = (
            self.tree.allowed_contexts
        )
        self._global_allowed_installs: app_commands.AppInstallationType = (
            self.tree.allowed_installs
        )
        self._application: discord.AppInfo | None = None
        self._app_user_installable: discord.IntegrationTypeConfig | None = None
        self._app_guild_installable: discord.IntegrationTypeConfig | None = None

    async def new_sync(self, *, guild: discord.Object | None = None) -> None:
        await self.check(guild=guild)
        if self.__original_tree_sync:
            await self.__original_tree_sync(guild=guild)

    async def store_application(self) -> discord.AppInfo:
        # fmt: off
        self._application = self._application or self.tree.client.application or await self.tree.client.application_info()
        self._app_guild_installable = self._application.guild_integration_config
        self._app_user_installable = self._application.user_integration_config
        return self._application

        # fmt: on

    def __is_bot_guild_installable(self) -> bool:
        if self._global_allowed_installs._guild is not None:
            return self._global_allowed_installs.guild

        if self._app_guild_installable is not None:
            return bool(self._app_guild_installable)

        return self._global_allowed_installs.guild

    def __is_bot_user_installable(self) -> bool:
        if self._global_allowed_installs._user is not None:
            return self._global_allowed_installs.user

        if self._app_user_installable is not None:
            return bool(self._app_user_installable)

        return self._global_allowed_installs.user

    def __is_bot_guild_usable(self) -> bool:
        if self._global_allowed_contexts._guild is not None:
            return self._global_allowed_contexts.guild

        return True

    def __is_bot_dm_usable(self) -> bool:
        if self._global_allowed_contexts._dm_channel is not None:
            return self._global_allowed_contexts.dm_channel

        return True

    def __is_bot_private_channel_usable(self) -> bool:
        if self._global_allowed_contexts._private_channel is not None:
            return self._global_allowed_contexts.private_channel

        return True

    def __is_command_guild_installable(self, command: CommandT) -> bool:
        allowed_installs = command.allowed_installs
        return allowed_installs.guild if allowed_installs is not None else True

    def __is_command_user_installable(self, command: CommandT) -> bool:
        allowed_installs = command.allowed_installs
        return allowed_installs.user if allowed_installs is not None else False

    def __is_command_guild_usable(self, command: CommandT) -> bool:
        allowed_contexts = command.allowed_contexts
        return allowed_contexts.guild if allowed_contexts is not None else True

    def __is_command_dm_usable(self, command: CommandT) -> bool:
        allowed_contexts = command.allowed_contexts
        return allowed_contexts.dm_channel if allowed_contexts is not None else True

    def __is_command_private_channel_usable(self, command: CommandT) -> bool:
        allowed_contexts = command.allowed_contexts
        return (
            allowed_contexts.private_channel if allowed_contexts is not None else False
        )

    def get_bot_debug_info(self) -> str:
        return (
            f"Bot installability and usability:\n"
            f"  Commands can be added to a server: {format_bool_none(self.__is_bot_guild_installable())}\n"
            f"  Commands can be added to an user: {format_bool_none(self.__is_bot_user_installable())}\n"
            f"  Commands can be used in a server: {format_bool_none(self.__is_bot_guild_usable())}\n"
            f"  Commands can be used in the bot's DMs: {format_bool_none(self.__is_bot_dm_usable())}\n"
            f"  Commands can be used in user or group DMs: {format_bool_none(self.__is_bot_private_channel_usable())}\n"
        )

    async def check_command(self, command: CommandT) -> _DebugableCommand:
        is_guild_installable = self.__is_command_guild_installable(command)
        is_user_installable = self.__is_command_user_installable(command)
        is_guild_usable = self.__is_command_guild_usable(command)
        is_dm_usable = self.__is_command_dm_usable(command)
        is_private_channel_usable = self.__is_command_private_channel_usable(command)

        if is_guild_installable and not self.__is_bot_guild_installable():
            msg = f"Command '{command.name}' is guild installable, but the bot is not guild installable."
            raise ValueError(msg)

        if is_user_installable and not self.__is_bot_user_installable():
            msg = f"Command '{command.name}' is user installable, but the bot is not user installable."
            raise ValueError(msg)

        if is_guild_usable and not self.__is_bot_guild_usable():
            msg = f"Command '{command.name}' is guild usable, but the bot is not guild usable."
            raise ValueError(msg)

        if is_dm_usable and not self.__is_bot_dm_usable():
            msg = (
                f"Command '{command.name}' is DM usable, but the bot is not DM usable."
            )
            raise ValueError(msg)

        if is_private_channel_usable and not self.__is_bot_private_channel_usable():
            msg = f"Command '{command.name}' is private channel usable, but the bot is not private channel usable."
            raise ValueError(msg)

        return _DebugableCommand(
            command,
            is_guild_installable=is_guild_installable,
            is_user_installable=is_user_installable,
            is_guild_usable=is_guild_usable,
            is_dm_usable=is_dm_usable,
            is_private_channel_usable=is_private_channel_usable,
        )

    async def check(self, *, guild: discord.Object | None = None):
        app = await self.store_application()

        if guild:
            guild_object: discord.Guild | None = (
                self.tree.client.get_guild(guild.id)
                if not isinstance(guild, discord.Guild)
                else guild
            )
            if not guild_object and not self.tree.client.intents.guilds:
                guild_object = await self.tree.client.fetch_guild(guild.id)

            if not guild_object:
                msg = f"Tried to sync to an unknown guild with ID {guild.id}."
                raise ValueError(msg)

            bot_integration = discord.utils.find(
                lambda integration: isinstance(integration, discord.BotIntegration)
                and integration.application.id == app.id,
                await guild_object.integrations(),
            )
            if not bot_integration:
                msg = f"The bot is not installed in the guild with ID {guild.id}."
                raise ValueError(msg)

            # !TODO: check scopes when dpy supports it, PR 10352
            # https://github.com/Rapptz/discord.py/pull/10352

            # fmt: on

        commands = list(self.tree.get_commands(guild=guild))
        if not commands:
            raise ValueError(
                f"No {'global commands' if not guild else f'commands for guild {guild.id}'} found to sync."
            )

        debugable_commands: list[_DebugableCommand] = []
        for command in commands:
            dcommand = await self.check_command(command)
            debugable_commands.append(dcommand)

        debug_info = {
            "bot": {
                "guild_installable": self.__is_bot_guild_installable(),
                "user_installable": self.__is_bot_user_installable(),
                "guild_usable": self.__is_bot_guild_usable(),
                "dm_usable": self.__is_bot_dm_usable(),
                "private_channel_usable": self.__is_bot_private_channel_usable(),
            },
            "commands": [
                {
                    "name": cmd.command.name,
                    "guild_installable": cmd.is_guild_installable,
                    "user_installable": cmd.is_user_installable,
                    "guild_usable": cmd.is_guild_usable,
                    "dm_usable": cmd.is_dm_usable,
                    "private_channel_usable": cmd.is_private_channel_usable,
                }
                for cmd in debugable_commands
            ],
        }
        with open("debug_info.json", "w", encoding="utf-8") as f:
            json.dump(debug_info, f, indent=2)
        print(
            self.get_bot_debug_info(),
            "Commands debug info:\n",
            "\n".join(f"{cmd}" for cmd in debugable_commands),
        )
