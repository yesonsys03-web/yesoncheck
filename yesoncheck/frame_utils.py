"""Frame calculation helpers for sheet length formatting."""


class FrameCalculator:
    @staticmethod
    def calculate_sheet_length(frames):
        try:
            frames = int(frames)
            return f"{frames // 16}.{frames % 16:02d}"
        except Exception:
            return "0.00"

    @staticmethod
    def format_feet_display(sheet_length):
        try:
            if not isinstance(sheet_length, str) or "." not in sheet_length:
                return "0F 00f"
            feet, frames = sheet_length.split(".")
            return f"{int(feet)}F {int(frames):02d}f"
        except Exception:
            return "0F 00f"
