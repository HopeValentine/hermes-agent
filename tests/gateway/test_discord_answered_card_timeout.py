"""A completed approval card must never be re-stamped as "expired".

``discord.py`` fires ``View.on_timeout`` when the view timer expires **even after
a button was clicked** — resolving the view does not stop the timer. The shared
handler used to stamp ``platform.discord.prompt.expired_footer`` over the embed
and set ``resolved = True``, so a COMPLETED approval flipped to "expired, nothing
ran" a few minutes later (observed live: the approve card flipped at +5 min
despite a successful approval, and the deny test card flipped the same way).
That stale state is exactly what invites a duplicate re-dispatch.

Only a genuinely unanswered prompt is marked expired; the buttons are disabled in
both cases.

The adapter's view classes are registered as module globals by
``_define_discord_view_classes()``, so ``ExecApprovalView`` (which inherits the
shared ``on_timeout``) is imported directly against a stubbed ``discord``.
"""

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


def _ensure_discord_mock():
    if "discord" in sys.modules and hasattr(sys.modules["discord"], "__file__"):
        return

    class _FakeView:
        """Minimal ``discord.ui.View`` stand-in — enough for the real view classes."""

        def __init__(self, *, timeout=None):
            self.timeout = timeout
            self.children = []

        def add_item(self, item):
            self.children.append(item)

        def remove_item(self, item):
            if item in self.children:
                self.children.remove(item)

        def clear_items(self):
            self.children.clear()

    class _FakeButton:
        def __init__(self, *, label="", style=None, custom_id=None, emoji=None, **kwargs):
            self.label = label
            self.style = style
            self.custom_id = custom_id
            self.emoji = emoji
            self.disabled = False
            self.callback = None

    discord_mod = MagicMock()
    discord_mod.Intents.default.return_value = MagicMock()
    discord_mod.Client = MagicMock
    discord_mod.File = MagicMock
    discord_mod.DMChannel = type("DMChannel", (), {})
    discord_mod.Thread = type("Thread", (), {})
    discord_mod.ForumChannel = type("ForumChannel", (), {})
    discord_mod.ui = SimpleNamespace(
        View=_FakeView,
        button=lambda *a, **k: (lambda fn: fn),
        Button=_FakeButton,
        Select=_FakeButton,
    )
    discord_mod.ButtonStyle = SimpleNamespace(
        success=1, primary=2, secondary=2, danger=3, green=1, grey=2, blurple=2, red=3
    )
    discord_mod.Color = SimpleNamespace(
        orange=lambda: 1, green=lambda: 2, blue=lambda: 3, red=lambda: 4, purple=lambda: 5,
        greyple=lambda: 6, dark_grey=lambda: 7,
    )
    discord_mod.Interaction = object
    discord_mod.Embed = MagicMock
    discord_mod.SelectOption = _FakeButton
    discord_mod.app_commands = SimpleNamespace(
        describe=lambda **kwargs: (lambda fn: fn),
        choices=lambda **kwargs: (lambda fn: fn),
        Choice=lambda **kwargs: SimpleNamespace(**kwargs),
    )

    ext_mod = MagicMock()
    commands_mod = MagicMock()
    commands_mod.Bot = MagicMock
    ext_mod.commands = commands_mod

    sys.modules.setdefault("discord", discord_mod)
    sys.modules.setdefault("discord.ext", ext_mod)
    sys.modules.setdefault("discord.ext.commands", commands_mod)


_ensure_discord_mock()

from agent.i18n import t  # noqa: E402
from plugins.platforms.discord.adapter import ExecApprovalView  # noqa: E402


def _patch_config(monkeypatch, cfg):
    import hermes_cli.config

    monkeypatch.setattr(hermes_cli.config, "read_raw_config", lambda: cfg)


class _Embed:
    def __init__(self):
        self.color = "original-color"
        self.footer = None

    def set_footer(self, *, text):
        self.footer = text


class _Message:
    def __init__(self, embed):
        self.embeds = [embed]
        self.edits = []

    async def edit(self, **kwargs):
        self.edits.append(kwargs)


def _view_with_buttons(monkeypatch):
    _patch_config(monkeypatch, {})
    view = ExecApprovalView(session_key="sess-1", allowed_user_ids={"42"})
    view.children = [SimpleNamespace(disabled=False), SimpleNamespace(disabled=False)]
    embed = _Embed()
    message = _Message(embed)
    view._message = message
    return view, embed, message


@pytest.mark.asyncio
async def test_answered_card_is_not_re_stamped_as_expired(monkeypatch):
    """The approval already happened: the timer firing must be a no-op on the embed."""
    view, embed, message = _view_with_buttons(monkeypatch)
    view.resolved = True

    await view.on_timeout()

    assert embed.footer is None
    assert embed.color == "original-color"
    assert message.edits == []
    assert all(child.disabled for child in view.children)


@pytest.mark.asyncio
async def test_unanswered_card_still_gets_the_expired_footer(monkeypatch):
    """The guard must not disarm the ordinary timeout path."""
    view, embed, message = _view_with_buttons(monkeypatch)

    await view.on_timeout()

    assert view.resolved is True
    assert embed.footer == t("platform.discord.prompt.expired_footer")
    assert embed.color == 6  # greyple
    assert len(message.edits) == 1
    assert all(child.disabled for child in view.children)
