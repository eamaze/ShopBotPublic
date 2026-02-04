import discord

class EmbedBuilder:
    """
    A standardized builder for creating Discord embeds.
    """
    def __init__(self, title: str = None, description: str = None, color: discord.Color = None):
        self._embed = discord.Embed(title=title, description=description, color=color)

    def set_title(self, title: str):
        self._embed.title = title
        return self

    def set_description(self, description: str):
        self._embed.description = description
        return self

    def set_color(self, color: discord.Color):
        self._embed.color = color
        return self

    def add_field(self, name: str, value: str, inline: bool = False):
        self._embed.add_field(name=name, value=value, inline=inline)
        return self

    def set_footer(self, text: str, icon_url: str = None):
        self._embed.set_footer(text=text, icon_url=icon_url)
        return self

    def set_author(self, name: str, url: str = None, icon_url: str = None):
        self._embed.set_author(name=name, url=url, icon_url=icon_url)
        return self

    def set_thumbnail(self, url: str):
        self._embed.set_thumbnail(url=url)
        return self

    def set_image(self, url: str):
        self._embed.set_image(url=url)
        return self
        
    def build(self) -> discord.Embed:
        return self._embed
