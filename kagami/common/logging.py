import logging
import discord

formatter = logging.Formatter('[%(asctime)s] [%(levelname)s] %(name)s: %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
discord_log_handler = logging.FileHandler(filename='discord.log', encoding='utf-8', mode='w')
bot_log_handler = logging.FileHandler(filename="bot.log", encoding="utf-8", mode='w')
discord_log_handler.setFormatter(formatter)
bot_log_handler.setFormatter(formatter)

def setup_logging(name: str):
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    logger.addHandler(bot_log_handler)
    return logger
