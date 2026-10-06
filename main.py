from datetime import datetime
import argparse
import asyncio
import json
import logging
import os
import random
import re
import sqlite3

#import aiohttp
from discord import app_commands
from discord.ext import commands
import discord

parser = argparse.ArgumentParser(description="Run the bot.")
parser.add_argument("-c", "--config", required=False, type=str, default="colorbot.conf", help="Config file, defaults to colorbot.conf.")
parser.add_argument("-l", "--log", required=False, type=str, default="colorbot.log", help="Log file, defaults to colorbot.log.")
parser.add_argument("-d", "--db", required=False, type=str, default="colorbot.db", help="Database file (SQLite), defaults to colorbot.db.")
parser.add_argument("--init-config", required=False, action="store_true", help="If specified, will initialize a config in --config")
parser.add_argument("--sync-tree", required=False, action="store_true", help="If specified, will sync the tree in all guilds upon loading")
args = parser.parse_args()

if args.init_config:
    config = {
        "discord-token": ""
    }
    fconfig = open(args.config, "w+")
    dumped = json.dumps(config, indent=4)
    fconfig.write(dumped)
    print("Config initialized in "+args.config+".")
    exit(0)

if os.path.isfile(args.config):
    fconfig = open(args.config, "r")
    config = json.loads(fconfig.read())
else:
    print("Please initialize the config with the flag --init-config.")
    exit(1)

if ("discord-token" not in config) or config["discord-token"] == "":
    print("No Discord token given, exiting.")
    exit(1)


# Ugly logging, might want to replace that at some point!
flog = open(args.log, "a")
def log(message: str) -> None:
    fmt = "["+datetime.today().strftime('%Y-%m-%d %H:%M:%S')+"] "+message
    print(fmt)
    flog.write("\n"+fmt)
    return None


dbcon = sqlite3.connect(args.db)

color_change_responses = [
    "All done, enjoy your color!",
    "Alrighty!",
    "Now you are colour!",
    "I guess the colour wasn't a lie...",
    "I gwess u can hav dis color... UwU :3",
    "Color assigned.",
    "beautiful color...",
    "Colors for everyone, including YOU!"
]
hex_code_regex = re.compile("#?[0-9a-fA-F]{6}")


intents = discord.Intents.default()
intents.members = True # probably optional. remove later?
colorbot = discord.Client(intents=intents)
tree = app_commands.CommandTree(colorbot)

def ensureTableExists(table: str) -> None:
    cursor = dbcon.cursor()
    cursor.execute("""
        SELECT name
        FROM sqlite_master
        WHERE type = 'table' AND name = ?
    """, ("g_"+table,))
    if cursor.fetchone() is None:
        cursor.execute(f"CREATE TABLE g_{table}(user_id int NOT NULL UNIQUE,role_id int NOT NULL)")
        dbcon.commit()
    return None

# Stolen from discord.py's doc
def is_guild_owner():
    def predicate(ctx):
        return ctx.guild is not None and ctx.guild.owner_id == ctx.author.id
    return commands.check(predicate)


@tree.command(
    name="color",
    description="Set your colour!"
)
@app_commands.describe(name='Name given to the role!')
@app_commands.describe(hex='The colour in hex!!!')
@app_commands.guild_only()
async def setcolor(interaction: discord.Interaction, hex: str, name: str|None):
    user_id = int(interaction.user.id)

    # Let's first parse the hex code!
    parsed_hex = hex_code_regex.search(hex)
    if parsed_hex == None:
        await interaction.response.send_message("Could not parse the hex code. Check for any typo?")
        return
    hex_code = parsed_hex.group(0) # We got the hex code!
    # Prefix the hex_code with #
    if hex_code[0] != "#":
        hex_code = "#"+hex_code
    color = discord.Colour.from_str(hex_code)

    ensureTableExists(str(interaction.guild_id))
    cursor = dbcon.cursor()
    cursor.execute(f"""
        SELECT role_id
        FROM g_{str(interaction.guild_id)}
        WHERE user_id == {str(user_id)}
    """)
    result = cursor.fetchone()
    if result is None:
        if name == None:
            await interaction.response.send_message("You don't have a color role yet and you didn't specify a role name, so no role could be created :(")
            return
        role = await interaction.guild.create_role(name=name, color=color, reason="Color role created by request from "+interaction.user.name)
        member = await guild.fetch_member(user.id)
        member.add_roles(role)
        log("Created "+role.name+" ("+str(role.id)+") in guild "+interaction.guild.name+" ("+str(interaction.guild_id)+") per request from "+str(user_id))
        cursor.execute(f"""
            INSERT INTO g_{str(interaction.guild_id)} VALUES
            ({str(user_id)}, {str(role.id)})
        """)
        dbcon.commit()
    else:
        role_id = int(result[0]) # should already be int anyway
        role = discord.utils.get(interaction.guild.roles, id=role_id)
        role.edit(color=color)
        log("Modified "+role.name+" ("+str(role.id)+") in guild "+interaction.guild.name+" ("+str(interaction.guild_id)+") per request from "+str(user_id))

    await interaction.response.send_message(random.choice(color_change_responses))
    return

@tree.command(
    name="registerrole",
    description="Register a role as a colour role, if you used other colour bots."
)
@app_commands.describe(role='Role to register.')
@app_commands.guild_only()
@commands.check_any(commands.has_guild_permissions(manage_roles=True), commands.has_guild_permissions(administrator=True), is_guild_owner())
async def registerrole(interaction: discord.Interaction, role: discord.Role):
    ensureTableExists(str(interaction.guild_id))
    cursor = dbcon.cursor()

    # I haven't found another way to pass the interaction to its own view. Feel free to tell me how if you know.
    dirty_hack = []

    class ConfirmView(discord.ui.View):
        def __init__(self, main_interaction: discord.Interaction):
            super().__init__()
            self.main_interaction = main_interaction

        @discord.ui.button(label="Yes", style=discord.ButtonStyle.green, emoji="✅")
        async def button_callback_yes(self, interaction: discord.Interaction, button: discord.Button):
            await interaction.response.defer()
            for user in role.members:
                cursor.execute(f"""
                    SELECT role_id
                    FROM g_{str(self.main_interaction.guild_id)}
                    WHERE user_id == {str(user.id)}
                """)
                result = cursor.fetchone()
                if result is None:
                    cursor.execute(f"""
                        INSERT INTO g_{str(self.main_interaction.guild_id)} VALUES
                        ({str(user.id)}, {str(role.id)})
                    """)
                    dbcon.commit()
            await dirty_hack[0].resource.edit(content=f"Role registered for all of its members!",view=None)

        @discord.ui.button(label="No", style=discord.ButtonStyle.red, emoji="✖️")
        async def button_callback_no(self, interaction: discord.Interaction, button: discord.Button):
            await dirty_hack[0].resource.edit(content="Understood, cancelling role registration.",view=None)

    if len(role.members) > 1:
        button1=discord.ui.Button(label="<",style=discord.ButtonStyle.green)
        dirty_hack.append(await interaction.response.send_message("This role is assigned to multiple members. Are you sure you want to do this?\nPlease note that any member with the role will be able to edit its colour.",view=ConfirmView(interaction)))
    elif len(role.members) == 1:
        cursor.execute(f"""
            SELECT role_id
            FROM g_{str(interaction.guild_id)}
            WHERE user_id == {role.members[0].id}
        """)
        result = cursor.fetchone()
        if result is None:
            cursor.execute(f"""
                INSERT INTO g_{str(interaction.guild_id)} VALUES
                ({str(role.members[0].id)}, {str(role.id)})
            """)
            dbcon.commit()
            await interaction.response.send_message(f"Role registered for its member!")
        else:
            await interaction.response.send_message(f"Only member already has a color role, so no registration done.")
    else:
        await interaction.response.send_message(f"Role has no member, so no registration done.")


    return


@colorbot.event
async def on_ready() -> None:
    if args.sync_tree:
        await tree.sync()
    log("Bot is ready!")
    return None


try:
    asyncio.run(colorbot.run(config["discord-token"]))
except Exception as e:
    dbcon.close()
    log("Exiting, exception:"+str(e))