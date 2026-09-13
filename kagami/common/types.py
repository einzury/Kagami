import discord
from typing import TypeAliasType, get_args

type MessageableChannel = discord.TextChannel | discord.VoiceChannel | discord.StageChannel | discord.Thread | discord.DMChannel | discord.PartialMessageable | discord.GroupChannel
type MessageableGuildChannel = discord.TextChannel | discord.VoiceChannel | discord.StageChannel | discord.Thread

def typeargs(type: TypeAliasType):
    return get_args(type.__value__)
