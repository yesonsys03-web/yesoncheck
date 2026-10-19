"""Aggregated VideoPlayer composed from modular components."""

from yesoncheck.player_annotations import PlayerAnnotationsMixin
from yesoncheck.player_base import VideoPlayerBase
from yesoncheck.player_playback import PlayerPlaybackMixin
from yesoncheck.player_sidebar import PlayerSidebarMixin
from yesoncheck.player_update import PlayerUpdateMixin


class VideoPlayer(PlayerUpdateMixin, PlayerAnnotationsMixin, PlayerSidebarMixin, PlayerPlaybackMixin, VideoPlayerBase):
    """Main window for the YesonCheck application."""
    pass
