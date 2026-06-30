import asyncio, time, subprocess
from collections.abc import Coroutine
from types import CoroutineType
from typing import Any, override
from discord import Message, TextChannel
import discord.utils
from discord.ext import commands
from discord import app_commands
from bot import Kagami, config
from subprocess import PIPE, Popen, STDOUT
from asyncio.subprocess import Process
from discord.abc import Messageable
import re

from common.logging import setup_logging

type Context = commands.Context[Kagami]

logger = setup_logging(__name__)

vs_chat_user = config.get("VS_CHAT_USER", str, "kagami")
vs_chat_key = config.get("VS_CHAT_KEY", str)
vs_chat_address = config.get("VS_CHAT_ADDRESS", str)
vs_chat_log_path = config.get("VS_CHAT_LOG_PATH", str)
vs_chat_script_path = config.get("VS_CHAT_SCRIPT_PATH", str)
vs_chat_screenname = config.get("VS_CHAT_SCREENNAME", str)

# Can't allocate pseudo-tty anyways so no need for -t
cmds = ["/usr/bin/ssh", "-T", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new", "-i", config.ssh_path + vs_chat_key, f"{vs_chat_user}@{vs_chat_address}"]

class VSChat(commands.Cog):
    def __init__(self, bot):
        self.bot: Kagami = bot
        self.channel: Messageable | None = None
        self.chat_relay: ChatRelay | None = None

    async def cog_load(self):
        if self.chat_relay is not None: await self.chat_relay.kill_processes()
        self.chat_relay = ChatRelay()

    @override
    async def cog_unload(self) -> None:
        if self.chat_relay is not None:
            await self.chat_relay.stop()
            self.chat_relay = None

    @commands.command(name="vs-screen", description="Send input via a screen console")
    @commands.is_owner()
    async def screen(self, ctx, *args):
        assert self.chat_relay is not None
        command = " ".join(args)

        ssh_cmd: str = " ".join(cmds)
        proc = await asyncio.create_subprocess_shell(ssh_cmd, stdin=PIPE, stdout=PIPE)
        if command.startswith("/"):
            command = command[1:]
            cmd = f" sudo -u vintagestory {vs_chat_script_path} command {command}\n"
            out, err = await proc.communicate(cmd.encode("utf-8"))
            out = "".join(out.decode("utf-8").splitlines(keepends=True)[8:])
            await ctx.send(f"Sent: `{command}`\nGot:\n```\n{out}```")
        else:
            cmd = f" sudo -u vintagestory screen -r {vs_chat_screenname} -X eval 'stuff \"{command}\"\\015'\n"
            # proc = await asyncio.create_subprocess_shell(ssh_cmd + cmd, stdin=PIPE, stdout=PIPE)
            # proc = await asyncio.create_subprocess_shell(ssh_cmd, stdin=PIPE, stdout=PIPE)
            out, err = await proc.communicate(cmd.encode("utf-8"))
            await ctx.send(f"Sent: `{command}`")
        # await ctx.send(f"Sent: `{command}`\nGot:\n```\n{out.decode("utf-8")}```")
        # out, err = await proc.communicate(f"sudo -u vintagestory screen -r {vs_chat_screenname} -X eval 'stuff \"{command}\"\\015'\n".encode("utf-8"))

    @commands.command(name="vs-startrelay")
    @commands.is_owner()
    async def start_listening(self, ctx: Context):
        if self.chat_relay is None:
            self.chat_relay = ChatRelay()
        assert self.chat_relay is not None
        if self.chat_relay.is_relaying:
            await ctx.send("Already Relaying")
            return
        await self.chat_relay.start(self.bot, ctx.channel)
        await ctx.send("Started Relay")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        assert self.chat_relay is not None
        if message.author != self.bot.user and message.channel == self.chat_relay.relay_channel:
            if self.chat_relay.is_relaying: 
                await self.chat_relay.relay_discord_to_game(message)

    @commands.command(name="vs-stoprelay")
    @commands.is_owner()
    async def stop_listening(self, ctx):
        if self.chat_relay is not None: 
            await self.chat_relay.stop()
            await ctx.send("Stopped Relay")


class ChatRelay:
    def __init__(self):
        self.proc_chatlog: Process | None=None
        self.proc_screen: Process | None=None
        self.ssh_cmd: str = " ".join(cmds)
        self.relay_channel: Messageable | None=None
        self.is_relaying: bool = False

    async def create_proc_chatlog(self):
        log_cmd = f" \'sudo -u vintagestory tail -fn 0 {vs_chat_log_path}\'"
        self.proc_chatlog = await asyncio.create_subprocess_shell(self.ssh_cmd + log_cmd, stdin=PIPE, stdout=PIPE)

    async def create_proc_screen(self):
        # screen_cmd = f" \'sudo -u vintagestory screen -r vintagestory_server\'" # -X eval 'stuff \"{command}\"\\015'
        # self.proc_screen = await asyncio.create_subprocess_shell(self.ssh_cmd + screen_cmd, stdin=PIPE, stdout=PIPE)
        self.proc_screen = await asyncio.create_subprocess_shell(self.ssh_cmd, stdin=PIPE, stdout=PIPE)

    async def create_processes(self):
        await self.create_proc_chatlog()
        await self.create_proc_screen()

    async def kill_processes(self):
        if self.proc_chatlog is not None: self.proc_chatlog.kill()
        if self.proc_screen is not None: self.proc_screen.kill()

    async def send_to_screen(self, command: str):
        if self.proc_screen is None:
            await self.create_proc_screen()
        assert self.proc_screen is not None
        assert self.proc_screen.stdin is not None
        # self.proc_screen.stdin.write(f"{command}\n".encode("utf-8"))
        self.proc_screen.stdin.write(
            f"sudo -u vintagestory \
            screen -r {vs_chat_screenname} -X \
            eval 'stuff \"{command}\"\\015'\n".encode("utf-8")
        )
        await self.proc_screen.stdin.drain()

    async def start(self, bot: Kagami, channel: Messageable):
        await self.create_processes()
        self.relay_channel = channel
        self.is_relaying = True
        bot.loop.create_task(self.listen_to_game())

    async def stop(self):
        await self.kill_processes()
        self.relay_channel = None
        self.is_relaying = False

    async def relay_discord_to_game(self, message: discord.Message):
        if not self.is_relaying: return
        # may need to add more escapes here if there are any more characters that break the chat
        content = message.content.replace(">", "&gt;").replace("<", "&lt;")
        logger.debug(f"relay_discord_to_game: Discord: {message.author.name} ~ {content}")
        await self.send_to_screen(f"Discord: [{message.author.name}] ~ {content}")

    async def relay_game_to_discord(self, line: str):
        if not self.is_relaying: return
        assert self.relay_channel is not None
        mididx = line.find(":",19)
        front = line[:mididx]
        back = line[mididx+1:]
        logger.debug(f"relay_game_to_discord: front:{front} back:{back}")
        name = front.split(" ")[-1]
        await self.relay_channel.send(f"[{name}] ~ {back}")

    async def listen_to_game(self):
        assert self.proc_chatlog is not None
        assert self.proc_chatlog.stdout is not None
        reader = self.proc_chatlog.stdout
        while self.is_relaying:
            raw_line = await reader.readline()
            if len(raw_line) == 0: continue
            line = raw_line.decode("utf-8")
            logger.debug(f"listen_to_game: {line}")
            pattern = r"^\d{1,2}\.\d{1,2}\.\d{4} \d{2}:\d{2}:\d{2} \[Chat] (?!Admin).*:.*"
            if re.match(pattern, line):
                await self.relay_game_to_discord(line)

async def setup(bot):
    await bot.add_cog(VSChat(bot))

