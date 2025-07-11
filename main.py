from dotenv import load_dotenv
import os
import requests
import asyncio
import discord
from discord.ext import commands, tasks
from keep_alive import keep_alive

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
API_KEY = os.getenv("YOUTUBE_API_KEY")
CHANNEL_ID = os.getenv("YOUTUBE_CHANNEL_ID")
DISCORD_CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID"))

intents = discord.Intents.default()
intents.message_content = True  # Important to read message content for commands

bot = commands.Bot(command_prefix="!", intents=intents)

last_video_id = None


async def fetch_latest_video():
    url = "https://www.googleapis.com/youtube/v3/search"
    params = {
        "key": API_KEY,
        "channelId": CHANNEL_ID,
        "part": "snippet",
        "order": "date",
        "maxResults": 1
    }
    response = requests.get(url, params=params)
    data = response.json()

    if "items" in data:
        video = data["items"][0]
        video_id = video["id"].get("videoId")
        title = video["snippet"]["title"]
        if video_id:
            return f"🔥 අලුත්ම Gameplay එක දාලා තියෙන්නෙ – \"{title}\" 😎💥\n👉 https://youtu.be/{video_id}"
    return "Sorry, no videos found."


async def fetch_channel_stats():
    url = "https://www.googleapis.com/youtube/v3/channels"
    params = {"key": API_KEY, "id": CHANNEL_ID, "part": "statistics"}
    response = requests.get(url, params=params)
    data = response.json()
    if "items" in data:
        stats = data["items"][0]["statistics"]
        return stats
    return None


# --- Helper Functions ---


async def fetch_playlists_with_mods():
    url = "https://www.googleapis.com/youtube/v3/playlists"
    params = {
        "key": API_KEY,
        "channelId": CHANNEL_ID,
        "part": "snippet",
        "maxResults": 50
    }
    response = requests.get(url, params=params)
    playlists = response.json().get("items", [])

    result = {}
    for pl in playlists:
        pl_id = pl["id"]
        pl_title = pl["snippet"]["title"]
        mod_videos = await fetch_mod_videos_from_playlist(pl_id)
        if mod_videos:
            result[pl_title] = mod_videos
    return result


async def fetch_mod_videos_from_playlist(playlist_id):
    url = "https://www.googleapis.com/youtube/v3/playlistItems"
    params = {
        "key": API_KEY,
        "playlistId": playlist_id,
        "part": "snippet",
        "maxResults": 50
    }
    response = requests.get(url, params=params)
    items = response.json().get("items", [])

    videos = []
    for item in items:
        video_id = item["snippet"]["resourceId"]["videoId"]
        video_title = item["snippet"]["title"]
        description = await fetch_video_description(video_id)
        if description and "mods used" in description.lower():
            videos.append({
                "id": video_id,
                "title": video_title,
                "description": description
            })
    return videos


async def fetch_video_description(video_id):
    url = "https://www.googleapis.com/youtube/v3/videos"
    params = {"key": API_KEY, "id": video_id, "part": "snippet"}
    response = requests.get(url, params=params)
    items = response.json().get("items", [])
    if items:
        return items[0]["snippet"].get("description")
    return None


# --- New interactive selection UI code ---


class PlaylistSelect(discord.ui.Select):

    def __init__(self, playlists):
        options = [
            discord.SelectOption(label=pl['snippet']['title'], value=pl['id'])
            for pl in playlists
        ]
        super().__init__(placeholder="Select a playlist...",
                         min_values=1,
                         max_values=1,
                         options=options)

    async def callback(self, interaction: discord.Interaction):
        playlist_id = self.values[0]
        url = "https://www.googleapis.com/youtube/v3/playlistItems"
        params = {
            "part": "snippet",
            "maxResults": 25,
            "playlistId": playlist_id,
            "key": API_KEY,
        }
        resp = requests.get(url, params=params).json()
        videos = resp.get("items", [])

        view = discord.ui.View()
        view.add_item(VideoSelect(videos))
        await interaction.response.edit_message(content="Select a video:",
                                                view=view)


class PlaylistView(discord.ui.View):

    def __init__(self, playlists):
        super().__init__()
        self.add_item(PlaylistSelect(playlists))


class VideoSelect(discord.ui.Select):

    def __init__(self, videos):
        options = []
        for v in videos:
            title = v['snippet']['title']
            video_id = v['snippet']['resourceId']['videoId']
            # Truncate title if too long for Discord limits
            if len(title) > 90:
                title = title[:87] + "..."
            options.append(discord.SelectOption(label=title, value=video_id))
        super().__init__(placeholder="Select a video...",
                         min_values=1,
                         max_values=1,
                         options=options)

    async def callback(self, interaction: discord.Interaction):
        video_id = self.values[0]
        url = f"https://youtu.be/{video_id}"
        await interaction.response.edit_message(
            content=f"Here's your video:\n{url}", view=None)


@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")


@bot.command(name="latest")
async def latest(ctx):
    message = await fetch_latest_video()
    await ctx.send(message)


@bot.command(name="subscribers")
async def subscribers(ctx):
    stats = await fetch_channel_stats()
    if stats:
        subs = stats.get("subscriberCount", "Unknown")
        await ctx.send(f"📊 Subscribers Count: {subs}")
    else:
        await ctx.send("Sorry, can't fetch subscriber count right now.")


@bot.command(name="stats")
async def stats(ctx):
    stats = await fetch_channel_stats()
    if stats:
        subs = stats.get("subscriberCount", "Unknown")
        vids = stats.get("videoCount", "Unknown")
        views = stats.get("viewCount", "Unknown")
        await ctx.send(
            f"📊 Channel Stats:\nSubscribers: {subs}\nTotal Videos: {vids}\nTotal Views: {views}"
        )
    else:
        await ctx.send("Sorry, can't fetch channel stats right now.")


# New command to get playlists and videos interactive selection
@bot.command(name="videos")
async def videos(ctx):
    url = "https://www.googleapis.com/youtube/v3/playlists"
    params = {
        "part": "snippet",
        "channelId": CHANNEL_ID,
        "maxResults": 25,
        "key": API_KEY
    }
    resp = requests.get(url, params=params).json()
    playlists = resp.get("items", [])

    if not playlists:
        await ctx.send("No playlists found on the channel.")
        return

    view = PlaylistView(playlists)
    await ctx.send("Select a playlist:", view=view)


async def background_video_check():
    await bot.wait_until_ready()
    global last_video_id

    # Find announcement channel by name
    target_channel = discord.utils.get(bot.get_all_channels(),
                                       name="kaviyagaming-announcement")

    if not target_channel:
        print("❌ 'kaviyagaming-announcement' channel not found!")
        return

    while not bot.is_closed():
        try:
            url = "https://www.googleapis.com/youtube/v3/search"
            params = {
                "key": API_KEY,
                "channelId": CHANNEL_ID,
                "part": "snippet",
                "order": "date",
                "maxResults": 1
            }
            response = requests.get(url, params=params)
            data = response.json()

            if "items" in data:
                video = data["items"][0]
                video_id = video["id"].get("videoId")
                title = video["snippet"]["title"]
                description = video["snippet"]["description"]
                publish_time = video["snippet"]["publishedAt"]

                if video_id and video_id != last_video_id:
                    last_video_id = video_id

                    embed = discord.Embed(
                        title="📢 අලුත්ම වීඩියෝ එක ආවා! 😎",
                        description=f"**{title}**\n\n{description[:200]}...",
                        color=discord.Color.red())
                    embed.add_field(name="📺 බලන්න මෙතනින්",
                                    value=f"https://youtu.be/{video_id}",
                                    inline=False)
                    embed.set_thumbnail(url="https://i.imgur.com/Tm0SRqc.png"
                                        )  # Small top right
                    embed.set_image(url="https://imgur.com/obg2Ruy.png"
                                    )  # Big image at bottom
                    embed.set_footer(
                        text="KaviyaGaming • Subscribe Now!",
                        icon_url="https://i.imgur.com/Tm0SRqc.png")

                    await target_channel.send(embed=embed)

        except Exception as e:
            print("❌ Video Auto-Post Error:", e)

        await asyncio.sleep(900)  # Check every 15 mins


# ✅ Basic ping command
@bot.command(name="ping")
async def ping(ctx):
    latency = round(bot.latency * 1000)  # in ms
    await ctx.send(f"🏓 Pong! Bot latency: `{latency}ms`")


# 🎮 Mod list display
# --- Discord UI View ---


@bot.command(name="modlist")
async def modlist(ctx):
    await ctx.send("🔎 Loading playlists with modded videos...")
    data = await fetch_playlists_with_mods()

    if not data:
        return await ctx.send("😢 No playlists found with mod info.")

    class PlaylistSelect(View):

        def __init__(self):
            super().__init__()
            options = [
                discord.SelectOption(label=pl_name, value=pl_name)
                for pl_name in data.keys()
            ]
            self.add_item(
                Select(placeholder="📂 Select a playlist",
                       options=options,
                       custom_id="select_playlist"))

        @discord.ui.select(custom_id="select_playlist")
        async def select_playlist(self, select: Select,
                                  interaction: Interaction):
            selected_playlist = select.values[0]
            videos = data[selected_playlist]
            video_options = [
                discord.SelectOption(label=vid["title"], value=vid["id"])
                for vid in videos
            ]

            class VideoSelect(View):

                def __init__(self):
                    super().__init__()
                    self.add_item(
                        Select(placeholder="🎬 Select a video",
                               options=video_options,
                               custom_id="select_video"))

                @discord.ui.select(custom_id="select_video")
                async def select_video(self, select: Select,
                                       interaction: Interaction):
                    video_id = select.values[0]
                    for vid in videos:
                        if vid["id"] == video_id:
                            mods_section = extract_mod_section(
                                vid["description"])
                            embed = Embed(
                                title=f"🔧 Mods Used in: {vid['title']}",
                                description=mods_section
                                or "No clear mods section found 😢",
                                color=discord.Color.dark_gold())
                            embed.add_field(
                                name="📺 Watch Video",
                                value=f"https://youtu.be/{video_id}",
                                inline=False)
                            return await interaction.response.send_message(
                                embed=embed)

            await interaction.response.send_message(view=VideoSelect(),
                                                    ephemeral=True)

    await ctx.send("📂 Select a playlist below:", view=PlaylistSelect())


    # 📋 Help command
@bot.command(name="commands")
async def help_command(ctx):
    embed = discord.Embed(
        title="🎮 KaviyaGamingBot Help Menu",
        description="ඔයාලට ඕනේ command ekak select karala balanna puluwan 😎",
        color=discord.Color.green())
    embed.add_field(name="`!latest`",
                    value="📺 Latest uploaded video link",
                    inline=False)
    embed.add_field(name="`!videos`",
                    value="📂 Playlist + video selection menu",
                    inline=False)
    embed.add_field(name="`!modlist`",
                    value="🛠️ Mods used in gameplay",
                    inline=False)
    embed.add_field(name="`!ping`", value="🏓 Test bot latency", inline=False)

    # 🖼️ Add visual elements
    embed.set_image(url="https://imgur.com/obg2Ruy.png")  # Bottom big image
    embed.set_thumbnail(
        url="https://i.imgur.com/Tm0SRqc.png")  # Top-right small image
    embed.set_footer(text="Powered by KaviyaGaming 🎮",
                     icon_url="https://i.imgur.com/Tm0SRqc.png")

    await ctx.send(embed=embed)


@bot.command(name="admin-commands")
async def admin_help_command(ctx):
    embed = discord.Embed(
        title="🎮 KaviyaGamingBot Help Menu",
        description="ඔයාලට ඕනේ command ekak select karala balanna puluwan 😎",
        color=discord.Color.green())
    embed.add_field(name="`!latest`",
                    value="📺 Latest uploaded video link",
                    inline=False)
    embed.add_field(name="`!videos`",
                    value="📂 Playlist + video selection menu",
                    inline=False)
    embed.add_field(name="`!subscribers`",
                    value="👥 Subscriber count",
                    inline=False)
    embed.add_field(name="`!stats`",
                    value="📊 Channel stats (views, videos)",
                    inline=False)
    embed.add_field(name="`!modlist`",
                    value="🛠️ Mods used in gameplay",
                    inline=False)
    embed.add_field(name="`!ping`", value="🏓 Test bot latency", inline=False)

    # 🖼️ Add visual elements
    embed.set_image(url="https://imgur.com/obg2Ruy.png")  # Bottom big image
    embed.set_thumbnail(
        url="https://i.imgur.com/Tm0SRqc.png")  # Top-right small image
    embed.set_footer(text="Powered by KaviyaGaming 🎮",
                     icon_url="https://i.imgur.com/Tm0SRqc.png")

    await ctx.send(embed=embed)


# --- Mod Section Extractor ---
def extract_mod_section(description):
    lines = description.splitlines()
    mod_lines = []
    recording = False
    for line in lines:
        if "mods used" in line.lower():
            recording = True
            continue
        if recording:
            if line.strip() == "" or line.lower().startswith("http"):
                mod_lines.append(line.strip())
            elif any(keyword in line.lower()
                     for keyword in ["music", "credit", "follow"]):
                break
            else:
                mod_lines.append(line.strip())
    return "\n".join(mod_lines).strip() if mod_lines else None
    # --- End of Mod Section Extractor ---

#-- start of the !stats command bot ---

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    auto_stats_command.start()

@tasks.loop(seconds=45)
async def auto_stats_command():
    target_channel = discord.utils.get(bot.get_all_channels(), name="privet-admin-room-3")

    if not target_channel:
        print("❌ Channel 'privet-admin-room-3' not found.")
        return

    try:
        # Send the response directly instead of pretending to call !stats
        stats_data = await fetch_channel_stats()
        if stats_data:
            subs = stats_data.get("subscriberCount", "Unknown")
            vids = stats_data.get("videoCount", "Unknown")
            views = stats_data.get("viewCount", "Unknown")
            message = (
                f"📊 Channel Stats:\n"
                f"Subscribers: {subs}\n"
                f"Total Videos: {vids}\n"
                f"Total Views: {views}"
            )
        else:
            message = "😢 Unable to fetch channel stats."

        await target_channel.send(message)

    except Exception as e:
        print("❌ Error running auto stats command:", e)


#-- end of the !stats command bot ---

keep_alive()
bot.run(DISCORD_TOKEN)
