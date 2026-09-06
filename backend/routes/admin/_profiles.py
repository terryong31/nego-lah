"""Shared user-identity helpers.

Both the user list and the chat list render a person, so the rule for *which*
avatar wins lives here rather than being duplicated (or, worse, diverging)
between them.
"""


def resolve_avatar_url(meta: dict, profile: dict | None = None) -> str | None:
    """The avatar to show for a user.

    `custom_avatar_url` is what the self-service profile page uploads. It wins
    over `avatar_url`, which Supabase re-syncs from the identity provider (i.e.
    the Google photo) on every OAuth sign-in. The legacy `user_profiles` row is
    the last resort, for users predating the move to auth metadata.
    """
    return (
        meta.get('custom_avatar_url')
        or meta.get('avatar_url')
        or (profile or {}).get('avatar_url')
    )
