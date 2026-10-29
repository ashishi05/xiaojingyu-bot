"""Resolve the owner's previously verified official private identity."""

OWNERS = {"10001", "10002"}
PRIMARY_SCOPE = "qqbot:FriendMessage:10001"
OFFICIAL_OWNER = ("default", "OFFICIAL_PRIVATE_OPENID")


def trusted_owner(event):
    """Return a trusted numeric owner ID without changing transport identity.

    Args:
        event: Incoming event from a trusted platform adapter.

    Returns:
        Canonical owner ID, or None for an unverified identity.
    """
    platform = event.get_platform_name()
    uid = str(event.get_sender_id())
    if platform == "aiocqhttp" and uid in OWNERS:
        return uid
    if (
        platform in {"qq_official", "qq_official_webhook"}
        and not event.get_group_id()
        and (event.get_platform_id(), uid) == OFFICIAL_OWNER
    ):
        return "10001"
    return None
