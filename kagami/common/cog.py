# common/cog.py
# A generic cog that my cogs inherit from for a base set of methods that are useful
from discord.ext.commands import Cog, GroupCog

from bot import Kagami

__all__ = ["KagamiCog"]

class KagamiCog(GroupCog):
    def __init__(self, bot: Kagami):
        self.bot = bot

    def conn(self, autocommit=False):
        return self.bot.dbman.conn(autocommit=autocommit)


