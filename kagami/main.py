import logging

import asyncio
from aiohttp import ClientSession
from bot import Kagami
import os
# from dotenv import load_dotenv, find_dotenv


def main():
    kagami = Kagami()
    asyncio.run(kagami())



if __name__ == '__main__':
    main()

