from typing import TYPE_CHECKING

import interactions.api.events as events
from interactions.models import PartialEmoji, Reaction, Message, Permissions

from ._template import EventMixinTemplate, Processor

if TYPE_CHECKING:
    from interactions.api.events import RawGatewayEvent

__all__ = ("ReactionEvents",)


class ReactionEvents(EventMixinTemplate):
    async def _check_message_fetch_permissions(self, channel_id: str, guild_id: str | None) -> bool:
        """
        Check if the bot has permissions to fetch a message in the given channel.

        Args:
            channel_id: The ID of the channel to check
            guild_id: The ID of the guild, if any

        Returns:
            bool: True if the bot has permission to fetch messages, False otherwise

        """
        if not guild_id:  # DMs always have permission
            return True

        channel = await self.cache.fetch_channel(channel_id)
        if not channel:
            return False

        bot_member = channel.guild.me
        ctx_perms = channel.permissions_for(bot_member)
        return Permissions.READ_MESSAGE_HISTORY in ctx_perms

    async def _handle_message_reaction_change(self, event: "RawGatewayEvent", add: bool) -> None:
        if member := event.data.get("member"):
            author = self.cache.place_member_data(event.data.get("guild_id"), member)
        elif guild_id := event.data.get("guild_id"):
            author = await self.cache.fetch_member(guild_id, event.data.get("user_id"))
        else:
            author = await self.cache.fetch_user(event.data.get("user_id"))

        emoji = PartialEmoji.from_dict(event.data.get("emoji"))  # type: ignore
        message = self.cache.get_message(event.data.get("channel_id"), event.data.get("message_id"))
        reaction = None

        if message:
            for i in range(len(message.reactions)):
                r = message.reactions[i]
                if r.emoji == emoji:
                    if add:
                        r.count += 1
                    else:
                        r.count -= 1

                    if r.count <= 0:
                        message.reactions.pop(i)
                    else:
                        message.reactions[i] = r
                    reaction = r
                    break
            else:
                reaction = Reaction.from_dict(
                    {
                        "count": 1,
                        "me": author.id == self.user.id,  # type: ignore
                        "emoji": emoji.to_dict(),
                        "message_id": message.id,
                        "channel_id": message._channel_id,
                    },
                    self,  # type: ignore
                )
                message.reactions.append(reaction)

        else:
            guild_id = event.data.get("guild_id")
            channel_id = event.data.get("channel_id")

            if await self._check_message_fetch_permissions(channel_id, guild_id):
                message = await self.cache.fetch_message(channel_id, event.data.get("message_id"))
                for r in message.reactions:
                    if r.emoji == emoji:
                        reaction = r
                        break

            if not message:  # otherwise construct skeleton message with no reactions
                message = Message.from_dict(
                    {
                        "id": event.data.get("message_id"),
                        "channel_id": channel_id,
                        "guild_id": guild_id,
                        "reactions": [],
                    },
                    self,
                )

        if add:
            self.dispatch(events.MessageReactionAdd(message=message, emoji=emoji, author=author, reaction=reaction))
        else:
            self.dispatch(events.MessageReactionRemove(message=message, emoji=emoji, author=author, reaction=reaction))

    @Processor.define()
    async def _on_raw_message_reaction_add(self, event: "RawGatewayEvent") -> None:
        await self._handle_message_reaction_change(event, add=True)

    @Processor.define()
    async def _on_raw_message_reaction_remove(self, event: "RawGatewayEvent") -> None:
        await self._handle_message_reaction_change(event, add=False)

    @Processor.define()
    async def _on_raw_message_reaction_remove_all(self, event: "RawGatewayEvent") -> None:
        if message := self.cache.get_message(event.data["channel_id"], event.data["message_id"]):
            message.reactions = []
        self.dispatch(
            events.MessageReactionRemoveAll(
                event.data.get("guild_id"),
                await self.cache.fetch_message(event.data["channel_id"], event.data["message_id"]),
            )
        )

    @Processor.define()
    async def _on_raw_message_reaction_remove_emoji(self, event: "RawGatewayEvent") -> None:
        emoji = PartialEmoji.from_dict(event.data.get("emoji"))
        message = self.cache.get_message(event.data.get("channel_id"), event.data.get("message_id"))

        if message:
            for i, reaction in enumerate(message.reactions):
                if reaction.emoji == emoji:
                    message.reactions.pop(i)
                    break
        else:
            message = await self.cache.fetch_message(event.data.get("channel_id"), event.data.get("message_id"))

        self.dispatch(
            events.MessageReactionRemoveEmoji(
                event.data.get("guild_id"),
                message,
                emoji,
            )
        )
