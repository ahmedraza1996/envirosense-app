"""Snap a building mask's outline onto the edges of the image it is drawn over.

Masks come from a model trained on labels that follow the before image, and the after image is a different capture, so
outlines can sit a metre or two off the roofs they describe. The shift that puts the outline on the strongest image edges
is measured over a small window; it is applied only when the edge response clearly peaks there.
"""
import cv2
import numpy as np

RADIUS = 12      # search window (+- px)
MIN_PEAK = 1.04  # best score / mean score over the window: below this the edges give no clear answer


def edge_strength(rgb: np.ndarray) -> np.ndarray:
    g = cv2.GaussianBlur(cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY).astype(np.float32), (0, 0), 1.5)
    return cv2.magnitude(cv2.Sobel(g, cv2.CV_32F, 1, 0), cv2.Sobel(g, cv2.CV_32F, 0, 1))


def surface(mask: np.ndarray, edges: np.ndarray, r: int = RADIUS) -> np.ndarray:
    """Mean edge strength under the mask outline, for every integer shift (dy, dx) in [-r, r]."""
    m = mask.astype(np.uint8)
    outline = (m - cv2.erode(m, np.ones((3, 3), np.uint8))).astype(np.float32)
    res = cv2.matchTemplate(edges, outline[r:-r, r:-r], cv2.TM_CCORR)
    return res / max(float(outline.sum()), 1.0)


def peak(s: np.ndarray, r: int = RADIUS):
    """Sub-pixel (dx, dy) of the surface maximum, and best / mean score (sharpness)."""
    i, j = np.unravel_index(np.argmax(s), s.shape)

    def sub(a, b, c):
        d = a - 2 * b + c
        return 0.0 if d == 0 else 0.5 * (a - c) / d
    dy = sub(s[i - 1, j], s[i, j], s[i + 1, j]) if 0 < i < s.shape[0] - 1 else 0.0
    dx = sub(s[i, j - 1], s[i, j], s[i, j + 1]) if 0 < j < s.shape[1] - 1 else 0.0
    return j - r + dx, i - r + dy, float(s[i, j] / max(float(s.mean()), 1e-6))


def edge_shift(mask: np.ndarray, rgb: np.ndarray, r: int = RADIUS):
    """(dx, dy, sharpness): move the mask by (dx, dy) to put its outline on the image's edges."""
    if mask.mean() < 0.002:
        return 0.0, 0.0, 0.0
    return peak(surface(mask, edge_strength(rgb), r), r)
