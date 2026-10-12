"""YesonCheck application package."""

__all__ = ["launch"]


def launch(argv=None):
    """앱 실행. PyQt5 등 무거운 모듈은 호출할 때 불러옵니다."""
    from .app import launch as _launch

    return _launch(argv)
