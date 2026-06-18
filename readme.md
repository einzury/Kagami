# Kagami
A discord bot made for use on small personal servers \
Probably has a lot of bugs that make it undesirable for large servers but it does have some fun features
## Hosting
Current Version: 0.8.6
### Local Hosting
- Lavalink Version [4.2.1](https://github.com/lavalink-devs/Lavalink/releases/tag/4.2.1)
  - The included [application config](./lavalink/application.yml) should suffice
  - Some lavalink plugins are also in use, the current version can be found in the above
### Building Docker Images
`docker build -f Dockerfile -t kagami_bot:amd64 .`

### Docker Compose

Just run `docker compose up -d` in the same directory as the compose.yaml files
- Lavalink should be hosted in a separate container from the bot but can be bundled using docker copose
  - Host networking should be enabled for proper interop
  

### Running Yourself
Create a venv for the project's requirements within the project directory \
`python -m venv .venv` \
Enter the venv \
Linux: `source .venv/bin/activate` \
Windows: `.venv/Scripts/activate.ps1` \
Now you can start the bot \
`python kagami/main.py`

This procedure assumes that you have just cloned the entire respository locally. \
By default the bot will attempt to run with music functionality which requires lavalink to be running in a seperate processes. 
If you do not want this then you can add "voice" to the "EXCLUDED_COGS" environment variable or remove the [voice module](./kagami/cogs/voice/) from the cogs directory.
Every module located under [cogs](./kagami/cogs/) can be disabled or removed without breaking anything else.

### Starting lavalink
Run the following command from the project source \
`python lavalink/lavalink.py` \
This does not need to be run within a virtual environment. \
The python scripts just serves to make it more convenient to start lavalink regardless of the host platform.
