from io import StringIO
from os import wait
from socket import gaierror
import asyncio, time, subprocess
from collections.abc import Coroutine
from types import CoroutineType
from typing import Any, Iterable, override
from discord import Message, TextChannel
import discord.utils
from discord.ext import commands
from discord import app_commands
from discord.abc import Messageable
from bot import Kagami, config
from subprocess import PIPE, Popen, STDOUT
from asyncio.subprocess import Process
from asyncio import StreamReader
import re

from common.logging import setup_logging

type Context = commands.Context[Kagami]

logger = setup_logging(__name__)

config_user = config.get("VSCHAT_USER", str, "kagami")
config_key = config.get("VSCHAT_KEY", str)
config_address = config.get("VSCHAT_ADDRESS", str)
config_log_path = config.get("VSCHAT_LOG_PATH", str)
config_file_chat = config.get("VSCHAT_FILE_SERVER_CHAT", str, "server-chat.log")
config_file_main = config.get("VSCHAT_FILE_SERVER_MAIN", str, "server-main.log")
config_file_audit = config.get("VSCHAT_FILE_SERVER_AUDIT", str, "server-audit.log")
config_path_script = config.get("VSCHAT_PATH_SCRIPT", str)
config_screenname = config.get("VSCHAT_SCREENNAME", str)

# Can't allocate pseudo-tty anyways so no need for -t
cmds = ["/usr/bin/ssh", "-T", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new", "-i", config.ssh_path + config_key, f"{config_user}@{config_address}"]

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

    @commands.group()
    async def vschat(self, ctx):
        pass

    @vschat.command(name="screen", description="Send input via a screen console")
    @commands.is_owner()
    async def screen(self, ctx, *args):
        assert self.chat_relay is not None
        command = " ".join(args)

        ssh_cmd: str = " ".join(cmds)
        proc = await asyncio.create_subprocess_shell(ssh_cmd, stdin=PIPE, stdout=PIPE, stderr=PIPE)
        if command.startswith("/"):
            command = command[1:]
            cmd = f" sudo -u vintagestory {config_path_script} command {command}\n"
            out, err = await proc.communicate(cmd.encode("utf-8"))
            out = "".join(out.decode("utf-8").splitlines(keepends=True)[8:])

            if len(out) > 2000:
                f = discord.File(StringIO(out), filename="out.txt")
                await ctx.send(f"Sent: `{command}`\nGot:", file=f)
            else:
                await ctx.send(f"Sent: `{command}`\nGot:\n```\n{out}```")
        else:
            cmd = f" sudo -u vintagestory screen -r {config_screenname} -X eval 'stuff \"{command}\"\\015'\n"
            # proc = await asyncio.create_subprocess_shell(ssh_cmd + cmd, stdin=PIPE, stdout=PIPE)
            # proc = await asyncio.create_subprocess_shell(ssh_cmd, stdin=PIPE, stdout=PIPE)
            out, err = await proc.communicate(cmd.encode("utf-8"))
            await ctx.send(f"Sent: `{command}`")
        # await ctx.send(f"Sent: `{command}`\nGot:\n```\n{out.decode("utf-8")}```")
        # out, err = await proc.communicate(f"sudo -u vintagestory screen -r {vs_chat_screenname} -X eval 'stuff \"{command}\"\\015'\n".encode("utf-8"))

    @vschat.group(name="relay", invoke_without_command=True)
    @commands.is_owner()
    async def relay(self, ctx: Context):
        new_relay = True
        if self.chat_relay is not None:
            if self.chat_relay.is_relaying: 
                await self.chat_relay.stop()
                await ctx.send("`Stopped the existing Relay`")
                new_relay = False
        else:
            self.chat_relay = ChatRelay()
        assert self.chat_relay is not None
        await self.chat_relay.start(self.bot, ctx.channel)
        if new_relay:
            await ctx.send("`Started the Relay`")
        else:
            await ctx.send("`Restarted the Relay`")

    @relay.command(name="start")
    @commands.is_owner()
    async def start_listening(self, ctx: Context):
        if self.chat_relay is None:
            self.chat_relay = ChatRelay()
        assert self.chat_relay is not None
        if self.chat_relay.is_relaying:
            await ctx.send("`The Relay is already Running`")
            return
        await self.chat_relay.start(self.bot, ctx.channel)
        await ctx.send("`Started the Relay`")

    @relay.command(name="stop")
    @commands.is_owner()
    async def stop_listening(self, ctx):
        if self.chat_relay is None or not self.chat_relay.is_relaying:
            await ctx.send("`The Relay is not Running`")
            return
        assert self.chat_relay is not None
        await self.chat_relay.stop()
        await ctx.send("`Stopped the Relay`")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if self.chat_relay is None: return
        if message.author == self.bot.user: return
        if message.channel != self.chat_relay.relay_channel: return

        if self.chat_relay.is_relaying: 
            await self.chat_relay.relay_discord(message)


class ChatRelay:
    def __init__(self):
        self.proc_log_chat: Process | None=None
        self.proc_log_main: Process | None=None
        self.proc_log_audit: Process | None=None
        self.proc_screen: Process | None=None
        self.ssh_cmd: str = " ".join(cmds)
        self.relay_channel: Messageable | None=None
        self.is_relaying: bool = False

    async def create_proc_log_chat(self):
        log_cmd = f" \'sudo -u vintagestory tail -fn 0 {config_log_path+config_file_chat}\'"
        self.proc_log_chat = await asyncio.create_subprocess_shell(self.ssh_cmd + log_cmd, stdin=None, stdout=PIPE, stderr=PIPE)

    async def create_proc_log_main(self):
        log_cmd = f" \'sudo -u vintagestory tail -fn 0 {config_log_path+config_file_main}\'"
        self.proc_log_main = await asyncio.create_subprocess_shell(self.ssh_cmd + log_cmd, stdin=None, stdout=PIPE, stderr=PIPE)

    async def create_proc_log_audit(self):
        log_cmd = f" \'sudo -u vintagestory tail -fn 0 {config_log_path+config_file_audit}\'"
        self.proc_log_audit = await asyncio.create_subprocess_shell(self.ssh_cmd + log_cmd, stdin=None, stdout=PIPE, stderr=PIPE)

    async def create_proc_screen(self):
        # screen_cmd = f" \'sudo -u vintagestory screen -r vintagestory_server\'" # -X eval 'stuff \"{command}\"\\015'
        # self.proc_screen = await asyncio.create_subprocess_shell(self.ssh_cmd + screen_cmd, stdin=PIPE, stdout=PIPE)
        self.proc_screen = await asyncio.create_subprocess_shell(self.ssh_cmd, stdin=PIPE, stdout=PIPE, stderr=PIPE)

    async def create_processes(self):
        try:
            await self.create_proc_log_chat()
            await self.create_proc_log_main()
            await self.create_proc_log_audit()
            await self.create_proc_screen()
        except gaierror as e:
            await self.kill_processes()
            logger.error(e)
            asyncio.sleep(5)
            await self.create_processes()

    async def kill_processes(self):
        if self.proc_log_chat  is not None: self.proc_log_chat.kill()
        if self.proc_log_main  is not None: self.proc_log_main.kill()
        if self.proc_log_audit is not None: self.proc_log_audit.kill()
        if self.proc_screen    is not None: self.proc_screen.kill()
        self.proc_log_chat = None
        self.proc_log_main = None
        self.proc_log_audit = None
        self.proc_screen = None

    async def start(self, bot: Kagami, channel: Messageable):
        await self.create_processes()
        self.relay_channel = channel
        self.is_relaying = True
        bot.loop.create_task(self.relay_audit())
        bot.loop.create_task(self.relay_chat())
        bot.loop.create_task(self.relay_main())

    async def stop(self):
        await self.kill_processes()
        self.relay_channel = None
        self.is_relaying = False

    # async def reset_screen(self):
    #     if self.proc_screen is None:
    #         await self.create_proc_screen()
    #     assert self.proc_screen is not None
    #     assert self.proc_screen.stdin is not None
    #     logger.debug(f"reset_screen")
    #     payload = (
    #         f"sudo -u vintagestory screen -r {config_screenname} -X "
    #         f"stuff $'\001:reset\015'\n"
    #     )
    #     self.proc_screen.stdin.write(payload.encode("utf-8"))
    #     await self.proc_screen.stdin.drain()

    async def send_to_game(self, command: str):
        if self.proc_screen is None:
            await self.create_proc_screen()
        assert self.proc_screen is not None
        assert self.proc_screen.stdin is not None
        # await self.reset_screen()
        logger.debug(f"send_to_game: {command}")
        # self.proc_screen.stdin.write(f"{command}\n".encode("utf-8"))
        payload = (
            f"sudo -u vintagestory screen -r {config_screenname} -X "
            f"stuff \"{command}\"\015\n"
        )
        # payload = (
        #     f"sudo -u vintagestory screen -r {config_screenname} -X "
        #     f"eval \'stuff \"{command}\"\\015\'\n"
        # )
        # payload = f"sudo -u vintagestory \
        #             screen -r {config_screenname} -X \
        #             eval 'stuff \"{command}\"\\015'\n"
        logger.debug(f"send_to_game: payload: {payload}")
        self.proc_screen.stdin.write(payload.encode("utf-8"))
        await self.proc_screen.stdin.drain()

    async def send_to_discord(self, content: str):
        assert self.relay_channel is not None
        content = (
            content
            .replace("&lt;strong&gt;", "**")
            .replace("&lt;/strong&gt;", "**")
            .replace("&lt;i&gt;", "*")
            .replace("&lt;/i&gt;", "*")
        )
        content = re.sub(r'&lt;a\s+href="([^"]*)"&gt;\s*(.*?)\s*&lt;/a&gt;', r'[\2](\1)', content)
        await self.relay_channel.send(content)

    async def relay_discord(self, message: discord.Message):
        if not self.is_relaying: return
        # may need to add more escapes here if there are any more characters that break the chat
        content = (
            message.content
            .replace(">", "&gt;")  
            .replace("<", "&lt;")  
            .replace("\\", "\\\\") 
            .replace('"', r'\"') 
            .replace("\n", "<br>") 
        )
        content = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", content)
        content = re.sub(r"\*(.+?)\*", r"<i>\1</i>", content)
        content = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', content)
        content = re.sub(r'(?<!\[)(?<!\()(https?://[^\s<>"\']+)', r'<a href="\1">\1</a>', content)

        logger.debug(f"relay_discord: [{message.author.name}] ~ {content}")
        # await self.send_to_game(f"Discord: [{message.author.name}] ~ {content}")
        await self.send_to_game(f"[{message.author.name}] ~ {content}")

    async def next_line(self, reader: StreamReader) -> str | None:
        raw_line = await reader.readline()
        if len(raw_line) == 0: return
        line = raw_line.decode("utf-8")
        # logger.debug(f"listen_for: {line}")
        return line

    async def relay_chat(self):
        assert   self.proc_log_chat        is not None
        assert   self.proc_log_chat.stdout is not None
        reader = self.proc_log_chat.stdout
        # pattern = r"^\d{1,2}\.\d{1,2}\.\d{4} \d{2}:\d{2}:\d{2} \[Chat] (?!Admin).*:(.*)"
        pattern = r"^\d{1,2}\.\d{1,2}\.\d{4} \d{2}:\d{2}:\d{2} \[Chat] \d \| (.*): (.*)"
        while self.is_relaying:
            line = await self.next_line(reader)
            if line is None: continue
            if m:=re.match(pattern, line):
                player = m.group(1)
                message = m.group(2)
                await self.send_to_discord(f"[{player}] ~ {message}")

    async def relay_audit(self):
        assert   self.proc_log_audit        is not None
        assert   self.proc_log_audit.stdout is not None
        reader = self.proc_log_audit.stdout
        # pattern = r"^\d{1,2}\.\d{1,2}\.\d{4} \d{2}:\d{2}:\d{2} \[Event] (.*) [.*]:.*\b"
        p_join     = r"^\d{1,2}\.\d{1,2}\.\d{4} \d{2}:\d{2}:\d{2} \[Audit] (.*) joined."
        p_leave    = r"^\d{1,2}\.\d{1,2}\.\d{4} \d{2}:\d{2}:\d{2} \[Audit] Client (.*) disconnected."
        p_death    = r"^\d{1,2}\.\d{1,2}\.\d{4} \d{2}:\d{2}:\d{2} \[Audit] (.*) died. Death message: (.*)"
        while self.is_relaying:
            line = await self.next_line(reader)
            if line is None: continue
            # logger.debug(f"listen_to_main: {line}")
            if m:=re.match(p_join, line):
                player = m.group(1)
                await self.send_to_discord(f"*{player} joined.*")
            elif m:=re.match(p_leave, line):
                player = m.group(1)
                await self.send_to_discord(f"*Player {player} left.*")
            elif m:=re.match(p_death, line):
                player = m.group(1)
                message = m.group(2)
                await self.send_to_discord(f"*{message}*")

    async def relay_main(self):
        assert   self.proc_log_main        is not None
        assert   self.proc_log_main.stdout is not None
        reader = self.proc_log_main.stdout
        # pattern = r"^\d{1,2}\.\d{1,2}\.\d{4} \d{2}:\d{2}:\d{2} \[Event] (.*) [.*]:.*\b"
        # p_join     = r"^\d{1,2}\.\d{1,2}\.\d{4} \d{2}:\d{2}:\d{2} \[Event] (.*) .* joins"
        # p_leave    = r"^\d{1,2}\.\d{1,2}\.\d{4} \d{2}:\d{2}:\d{2} \[Event] Player (.*) left"
        p_announce = r"^\d{1,2}\.\d{1,2}\.\d{4} \d{2}:\d{2}:\d{2} \[Event] Console Admin announced: (.*)\."
        while self.is_relaying:
            line = await self.next_line(reader)
            if line is None: continue
            # logger.debug(f"listen_to_main: {line}")
            if m:=re.match(p_announce, line):
                announcement = m.group(1)
                await self.send_to_discord(f"***{announcement}***")

async def setup(bot: Kagami):
    await bot.add_cog(VSChat(bot))

