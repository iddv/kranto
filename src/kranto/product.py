"""The product's name and every name computed from it, in one place.

Sentences say "Kranto" as written; anything a program computes from the name (the command, the
unit, the folders, the variable prefix, the MCP server, the User-Agent, the repository) reads it
from here. Standard library only, and it imports nothing of Kranto, so the update helper and
``legacy`` may read it.
"""

NAME = "Kranto"                  # in a sentence
COMMAND = "kranto"               # typed
DIST = "kranto"                  # the distribution; a version is read from DIST, then legacy.DISTS
ENV_PREFIX = "KRANTO_"
UNIT = "kranto.service"          # a new install's systemd user unit
CONFIG_DIR = "kranto"            # ~/.config/kranto
HOME_FILE = "kranto.yaml"        # a home's settings file
DB_FILE = "kranto.db"            # a home's library, under data/
DEFAULT_HOME = "~/.kranto"
DEFAULT_LOOP_HOME = "~/kranto-loop"
MCP_SERVER = "kranto"            # tools are f"{MCP_SERVER}_{verb}"
COOKIE = "kranto_session"
USER_AGENT = "kranto"            # f"{USER_AGENT}/{version} (+{SITE})", f"{USER_AGENT}-telemetry/1"
REPO = "iddv/kranto"
SITE = "https://github.com/" + REPO
