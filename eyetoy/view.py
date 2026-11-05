"""Digital zoom geometry, kept free of Tk so it can be tested on its own."""

from __future__ import annotations

MIN_ZOOM, MAX_ZOOM = 1.0, 6.0


def crop_box(width: int, height: int, zoom: float,
             center: tuple[float, float]) -> tuple[int, int, int, int] | None:
    """The source rectangle shown at ``zoom``, or None when nothing is cropped.

    ``center`` is the crop centre in normalised coordinates, so panning
    survives a resolution change. The height is derived from the width so the
    crop keeps the source aspect ratio exactly, and the box is clamped to stay
    inside the frame however far the centre is dragged.
    """
    if zoom <= 1.001:
        return None
    crop_w = min(width, max(32, int(width / zoom)))
    crop_h = min(height, max(24, round(crop_w * height / width)))
    left = int(center[0] * width - crop_w / 2)
    top = int(center[1] * height - crop_h / 2)
    left = min(width - crop_w, max(0, left))
    top = min(height - crop_h, max(0, top))
    return left, top, left + crop_w, top + crop_h
