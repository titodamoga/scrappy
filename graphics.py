from __future__ import annotations

import io

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

MIN_RADIUS = 6
MAX_RADIUS = 13


def _gray(data: bytes) -> np.ndarray:
    return np.array(Image.open(io.BytesIO(data)).convert('L'))


def _circles(gray: np.ndarray) -> list[tuple[int, int, int]]:
    found = cv2.HoughCircles(gray, cv2.HOUGH_GRADIENT, dp=1, minDist=18,
                             param1=90, param2=18, minRadius=MIN_RADIUS, maxRadius=MAX_RADIUS)
    if found is None:
        return []
    return [tuple(int(v) for v in c) for c in np.round(found[0]).astype(int)]


def _ink(gray: np.ndarray, cx: int, cy: int, half: int = 11) -> float:
    y0, y1 = max(0, cy - half), min(gray.shape[0], cy + half)
    x0, x1 = max(0, cx - half), min(gray.shape[1], cx + half)
    patch = gray[y0:y1, x0:x1]
    if patch.size == 0:
        return 0.0
    return float((patch < 110).mean())


def _group(values: list[int], tolerance: int = 12) -> list[tuple[int, list[int]]]:

    groups: list[list[int]] = []
    for value in sorted(values):
        if groups and value - groups[-1][-1] <= tolerance:
            groups[-1].append(value)
        else:
            groups.append([value])
    return [(int(round(sum(g) / len(g))), g) for g in groups]


def _radio_grid(gray: np.ndarray) -> tuple[list[int], list[int]] | None:

    circles = _circles(gray)
    if len(circles) < 6:
        return None
    columns = [(center, members) for center, members in _group([c[0] for c in circles])
               if len(members) >= 3]
    rows = [(center, members) for center, members in _group([c[1] for c in circles])
            if len(members) >= 2]
    if len(columns) != 2 or len(rows) < 3:
        return None
    counts = sorted(len(members) for _center, members in columns)
    if counts[0] != counts[1] or counts[1] < len(rows):
        return None
    return [c for c, _ in columns], [r for r, _ in rows]


def _grid_positions(circles: list[tuple[int, int, int]], xs: list[int], ys: list[int]):

    cells = {}
    for cx, cy, _r in circles:
        col = min(range(len(xs)), key=lambda i: abs(xs[i] - cx))
        row = min(range(len(ys)), key=lambda i: abs(ys[i] - cy))
        if abs(xs[col] - cx) <= 16 and abs(ys[row] - cy) <= 16:
            cells.setdefault((row, col), (cx, cy))
    return cells


def _homography(source: np.ndarray, target: np.ndarray) -> np.ndarray | None:

    orb = cv2.ORB_create(nfeatures=5000)
    k_src, d_src = orb.detectAndCompute(source, None)
    k_dst, d_dst = orb.detectAndCompute(target, None)
    if d_src is None or d_dst is None:
        return None
    matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
    matches = sorted(matcher.match(d_src, d_dst), key=lambda m: m.distance)[:250]
    if len(matches) < 20:
        return None
    src = np.float32([k_src[m.queryIdx].pt for m in matches]).reshape(-1, 1, 2)
    dst = np.float32([k_dst[m.trainIdx].pt for m in matches]).reshape(-1, 1, 2)
    matrix, mask = cv2.findHomography(src, dst, cv2.RANSAC, 4.0)
    if matrix is None or mask is None or int(mask.sum()) < 15:
        return None
    return matrix


def hotspot_grid(question_image: bytes, answer_image: bytes) -> dict | None:

    try:
        q_gray = _gray(question_image)
        a_gray = _gray(answer_image)
    except Exception:
        return None
    grid = _radio_grid(q_gray)
    if not grid:
        return None
    xs, ys = grid
    cells = _grid_positions(_circles(q_gray), xs, ys)
    if len(cells) < len(xs) * len(ys):
        return None


    matrix = _homography(a_gray, q_gray)
    if matrix is None:
        return None
    inverse = np.linalg.inv(matrix)

    rects, inks = [], []
    for row in range(len(ys)):
        for col in range(len(xs)):
            cx, cy = cells[(row, col)]
            if _ink(q_gray, cx, cy, half=5) > 0.20:
                return None
            rects.append((cx - 16, cy - 17, cx + 16, cy + 17))
            point = cv2.perspectiveTransform(np.float32([[[cx, cy]]]), inverse)[0][0]
            ax, ay = int(round(point[0])), int(round(point[1]))
            if not (0 <= ax < a_gray.shape[1] and 0 <= ay < a_gray.shape[0]):
                return None

            best = max(_ink(a_gray, ax + dx, ay + dy)
                       for dx in (-3, 0, 3) for dy in (-3, 0, 3))
            inks.append(best)


    low, high = min(inks), max(inks)
    if high < 0.18 or high - low < 0.12:
        return None
    limit = low + (high - low) / 2
    correct = [i for i, value in enumerate(inks) if value >= limit]
    if any(sum(row * len(xs) <= i < (row + 1) * len(xs) for i in correct) != 1
           for row in range(len(ys))):
        return None
    return {'rects': rects, 'correct': correct}


def _norm(gray: np.ndarray, width: int = 1000) -> np.ndarray:

    height = max(1, int(round(gray.shape[0] * width / gray.shape[1])))
    return cv2.resize(gray, (width, height), interpolation=cv2.INTER_AREA)


def _thick(gray: np.ndarray, iterations: int = 3) -> np.ndarray:

    binary = (gray < 110).astype(np.uint8)
    core = cv2.erode(binary, np.ones((3, 3), np.uint8), iterations=iterations)
    if not core.any():
        return np.zeros_like(binary)
    return cv2.dilate(core, np.ones((3, 3), np.uint8), iterations=iterations)


def mark_boxes(gray: np.ndarray, thick=None) -> list[tuple[int, int, int, int]]:

    thick = _thick(gray) if thick is None else thick
    found = []
    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(thick, 8)
    for index in range(1, count):
        x, y, w, h, area = stats[index]
        if w < 24 or h < 11 or w > gray.shape[1] * 0.8:
            continue
        if not 0.05 <= area / float(w * h) <= 0.85:
            continue
        found.append((int(x), int(y), int(w), int(h)))
    return found


def _merge_mark_fragments(gray: np.ndarray, fragments: list[tuple[int, int, int, int]]) -> list[tuple[int, int, int, int]]:

    boxes = [(x, y, x+w, y+h) for x, y, w, h in fragments]
    changed = True
    while changed:
        changed = False
        for i, a in enumerate(boxes):
            for j in range(i + 1, len(boxes)):
                b = boxes[j]
                vertical = max(0, min(a[3], b[3]) - max(a[1], b[1]))
                if vertical < .5 * min(a[3]-a[1], b[3]-b[1]):
                    continue
                left, right = sorted((a, b), key=lambda r: r[0])
                gap = right[0] - left[2]
                connected = gap <= 3
                if gap > 3:
                    y0 = max(0, min(left[1], right[1]) - 4)
                    y1 = min(gray.shape[0], max(left[3], right[3]) + 4)
                    patch = gray[y0:y1, left[2]:right[0]] < 110
                    if patch.size:
                        density = patch.mean(axis=1)
                        edge = min(10, len(density))
                        connected = max(density[:edge]) > .75 and max(density[-edge:]) > .75
                if not connected:
                    continue
                boxes[i] = (min(a[0], b[0]), min(a[1], b[1]),
                            max(a[2], b[2]), max(a[3], b[3]))
                boxes.pop(j)
                changed = True
                break
            if changed:
                break
    return boxes


def hotspot_marks(question_image: bytes, answer_image: bytes, iterations: int = 3) -> dict | None:


    try:
        q_gray = _norm(_gray(question_image))
        a_gray = _norm(_gray(answer_image))
    except Exception:
        return None
    matrix = _homography(a_gray, q_gray)
    if matrix is None:
        return None
    thick_q = _thick(q_gray, iterations)
    boxes = []
    fragments = mark_boxes(a_gray, _thick(a_gray, iterations))
    for x, y, right, bottom in _merge_mark_fragments(a_gray, fragments):
        corners = np.float32([[[x, y], [right, y], [x, bottom], [right, bottom]]])
        mapped = cv2.perspectiveTransform(corners, matrix)[0]
        x0, y0 = mapped.min(0)
        x1, y1 = mapped.max(0)
        x0, y0 = max(0, int(x0)), max(0, int(y0))
        x1, y1 = min(q_gray.shape[1], int(x1)), min(q_gray.shape[0], int(y1))
        if x1 - x0 < 24 or y1 - y0 < 11:
            continue

        if thick_q[y0:y1, x0:x1].mean() > 0.5:
            continue
        boxes.append((x0, y0, x1, y1))
    if not 1 <= len(boxes) <= 6:
        return None


    for i, a in enumerate(boxes):
        for b in boxes[i + 1:]:
            vertical = max(0, min(a[3], b[3]) - max(a[1], b[1]))
            horizontal = max(0, min(a[2], b[2]) - max(a[0], b[0]))
            if (vertical >= .5 * min(a[3] - a[1], b[3] - b[1])
                    or (vertical > 0 and horizontal >= .5 * min(a[2] - a[0], b[2] - b[0]))):
                return None

    keep = []
    for box in sorted(boxes, key=lambda b: (b[1], b[0])):
        if any(_overlap(box, other) > 0.6 for other in keep):
            continue
        keep.append(box)
    if not keep:
        return None
    scale = _gray(question_image).shape[1] / 1000.0
    rects = [(int(x0 * scale) - 4, int(y0 * scale) - 4,
              int(x1 * scale) + 4, int(y1 * scale) + 4) for x0, y0, x1, y1 in keep]


    original = _gray(question_image)
    grid = _radio_grid(original)
    if grid:
        cells = _grid_positions(_circles(original), *grid)


        if (len(cells) != len(grid[0]) * len(grid[1])
                or any(_ink(original, cx, cy, half=5) > .20 for cx, cy in cells.values())):
            grid = None
    if grid:
        xs, ys = grid
        if len(rects) != len(ys):
            return None
        rows = []
        for x0, y0, x1, y1 in rects:
            matches = [(row, col) for row, cy in enumerate(ys) for col, cx in enumerate(xs)
                       if x0-8 <= cx <= x1+8 and y0-8 <= cy <= y1+8]
            if len(matches) != 1:
                return None
            rows.append(matches[0][0])
        if sorted(rows) != list(range(len(ys))):
            return None
    return {'rects': rects, 'correct': list(range(len(rects)))}


def hotspot_dropdown(question_image: bytes, detected: dict) -> dict | None:

    if len(detected['rects']) != 1:
        return None
    gray = _gray(question_image)
    height, width = gray.shape
    x0, y0, x1, y1 = detected['rects'][0]
    mx, my = (x0 + x1) / 2, (y0 + y1) / 2
    contours, _ = cv2.findContours((gray < 235).astype(np.uint8),
                                   cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    candidates = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if not (.08 * width < w < .9 * width and 2 * (y1-y0) < h < .9 * height
                and x-20 <= mx <= x+w+20 and y <= my <= y+h
                and cv2.contourArea(contour) / (w*h) > .75):
            continue
        candidates.append((x, y, w, h))
    if not candidates:
        return None

    candidates.sort(key=lambda r: r[2] * r[3])
    x, y, w, h = candidates[0]


    if not any(by < y - 5 and bx-4 <= x and x+w <= bx+bw+4
               and y+h <= by+bh+4 for bx, by, bw, bh in candidates[1:]):
        return None
    for bx, by, bw, bh in candidates[1:]:
        if not (bx-4 <= x and by-4 <= y and x+w <= bx+bw+4 and y+h <= by+bh+4):
            return None
    crop = (gray[y:y+h, x+4:x+w-4] < 150).astype(np.uint8)
    if not crop.size:
        return None
    count, labels, stats, _ = cv2.connectedComponentsWithStats(crop, 8)
    clean = np.zeros_like(crop)
    for i, (_, _, cw, ch, area) in enumerate(stats[1:], 1):
        if (2 <= cw <= width * .1 and 4 <= ch <= height * .16
                and area >= 4 and cw / ch < 8):
            clean[labels == i] = 1
    density = clean.sum(axis=1)
    active = np.where(density >= max(4, int(w * .012)))[0]
    lines = []
    for row in active:
        if lines and row - lines[-1][-1] <= 3:
            lines[-1].append(int(row))
        else:
            lines.append([int(row)])
    lines = [line for line in lines if line[-1] - line[0] >= 3]
    if not 2 <= len(lines) <= 8:
        return None
    centers = np.array([y + (line[0] + line[-1]) / 2 for line in lines])
    gaps = np.diff(centers)
    step = float(np.median(gaps))
    if step < 12 or np.any(np.abs(gaps - step) > step * .2):
        return None

    if abs((centers[0] - step/2) - y) > step * .45 or abs((centers[-1] + step/2) - (y+h)) > step * .45:
        return None
    chosen = [i for i, center in enumerate(centers) if y0 <= center <= y1]
    if len(chosen) != 1:
        return None
    borders = [y] + [round((a+b)/2) for a, b in zip(centers, centers[1:])] + [y+h]
    return {'rects': [(x, borders[i], x+w, borders[i+1]) for i in range(len(lines))],
            'correct': chosen}


def hotspot_complete_grid(question_image: bytes, detected: dict) -> dict | None:

    selected = detected['rects']
    if len(selected) < 2:
        return None
    gray = _gray(question_image)
    circles = [c for c in _circles(gray) if _ink(gray, c[0], c[1], half=5) <= .20]
    rows = sorted((box[1] + box[3]) / 2 for box in selected)
    if min(np.diff(rows)) < 25:
        return None
    candidates = []
    for row in rows:
        candidates.extend(c for c in circles if abs(c[1] - row) <= 20)
    columns = [(x, values) for x, values in _group([c[0] for c in candidates])
               if len(values) == len(rows)]
    if len(columns) != 2:
        return None
    xs = [x for x, _ in columns]
    rects, correct = [], []
    for row_index, row in enumerate(rows):
        matched = []
        for col, x in enumerate(xs):
            possible = [(cx, cy, r) for cx, cy, r in circles
                        if abs(cx - x) <= 12 and abs(cy - row) <= 20]
            if len(possible) != 1:
                return None
            cx, cy, radius = possible[0]
            size = max(14, radius + 7)
            rects.append((max(0, cx-size), max(0, cy-size),
                          min(gray.shape[1], cx+size), min(gray.shape[0], cy+size)))
            if any(x0-8 <= cx <= x1+8 and y0-8 <= cy <= y1+8
                   for x0, y0, x1, y1 in selected):
                matched.append(row_index * 2 + col)
        if len(matched) != 1:
            return None
        correct.extend(matched)
    return {'rects': rects, 'correct': correct}


def _overlap(a, b) -> float:
    x0, y0 = max(a[0], b[0]), max(a[1], b[1])
    x1, y1 = min(a[2], b[2]), min(a[3], b[3])
    if x1 <= x0 or y1 <= y0:
        return 0.0
    intersection = (x1 - x0) * (y1 - y0)
    area = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return intersection / float(area or 1)


def hotspot_grid_norm(question_image: bytes, answer_image: bytes) -> dict | None:


    try:
        q_gray = _gray(question_image)
        a_gray = _gray(answer_image)
    except Exception:
        return None
    qn, an = _norm(q_gray), _norm(a_gray)
    circles = _circles_scaled(qn)
    if len(circles) < 4:
        return None
    columns = [(center, members) for center, members in _group([c[0] for c in circles])
               if len(members) >= 2]
    rows = [(center, members) for center, members in _group([c[1] for c in circles])
            if len(members) >= 2]
    if not 2 <= len(columns) <= 4 or len(rows) < 2:
        return None
    counts = [len(members) for _center, members in columns]
    if min(counts) != max(counts) or counts[0] < len(rows):
        return None
    xs = [center for center, _members in columns]
    ys = [center for center, _members in rows]
    cells = _grid_positions_scaled(circles, xs, ys)
    if len(cells) < len(xs) * len(ys):
        return None
    matrix = _homography(an, qn)
    if matrix is None:
        return None
    inverse = np.linalg.inv(matrix)
    rects, inks = [], []
    for row in range(len(ys)):
        for col in range(len(xs)):
            cx, cy = cells[(row, col)]
            if _ink(qn, cx, cy) > 0.20:
                return None
            rects.append((cx, cy))
            point = cv2.perspectiveTransform(np.float32([[[cx, cy]]]), inverse)[0][0]
            ax, ay = int(round(point[0])), int(round(point[1]))
            if not (0 <= ax < an.shape[1] and 0 <= ay < an.shape[0]):
                return None
            inks.append(max(_ink(an, ax + dx, ay + dy)
                            for dx in (-4, 0, 4) for dy in (-4, 0, 4)))
    low, high = min(inks), max(inks)
    if high < 0.18 or high - low < 0.10:
        return None
    limit = low + (high - low) / 2
    correct = [i for i, value in enumerate(inks) if value >= limit]


    if any(sum(row * len(xs) <= i < (row + 1) * len(xs) for i in correct) != 1
           for row in range(len(ys))):
        return None
    scale = q_gray.shape[1] / 1000.0
    boxes = [(int(cx * scale) - 16, int(cy * scale) - 17,
              int(cx * scale) + 16, int(cy * scale) + 17) for cx, cy in rects]
    return {'rects': boxes, 'correct': correct}


def _circles_scaled(gray: np.ndarray) -> list[tuple[int, int, int]]:
    found = cv2.HoughCircles(gray, cv2.HOUGH_GRADIENT, dp=1, minDist=26,
                             param1=90, param2=16, minRadius=8, maxRadius=18)
    if found is None:
        return []
    return [tuple(int(v) for v in c) for c in np.round(found[0]).astype(int)]


def _grid_positions_scaled(circles, xs, ys, tolerance: int = 22):
    cells = {}
    for cx, cy, _r in circles:
        col = min(range(len(xs)), key=lambda i: abs(xs[i] - cx))
        row = min(range(len(ys)), key=lambda i: abs(ys[i] - cy))
        if abs(xs[col] - cx) <= tolerance and abs(ys[row] - cy) <= tolerance:
            cells.setdefault((row, col), (cx, cy))
    return cells


def _drag_rectangles(gray: np.ndarray, threshold: int = 200) -> list[tuple[int, int, int, int]]:

    binary = cv2.threshold(gray, threshold, 255, cv2.THRESH_BINARY_INV)[1]
    contours, _ = cv2.findContours(binary, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    found = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if not (20 < w < gray.shape[1] * .8 and 12 < h < gray.shape[0] * .4
                and w / h >= 1.5 and cv2.contourArea(contour) / (w * h) >= .7):
            continue
        if any(abs(x-a) < 6 and abs(y-b) < 6 and abs(w-c) < 8 and abs(h-d) < 8
               for a, b, c, d in found):
            continue
        found.append((x, y, w, h))
    return found


def _drag_text(gray: np.ndarray, rect: tuple[int, int, int, int]) -> np.ndarray | None:

    x, y, w, h = rect
    patch = gray[y + int(h * .13):y + int(h * .87),
                 x + int(w * .16):x + w - max(1, int(w * .03))]
    binary = (patch < 155).astype(np.uint8) * 255
    count, labels, stats, _ = cv2.connectedComponentsWithStats(binary, 8)
    for index in range(1, count):
        if stats[index, 4] < 2:
            binary[labels == index] = 0
    ys, xs = np.where(binary > 0)
    if len(xs) < 10:
        return None
    return binary[ys.min():ys.max() + 1, xs.min():xs.max() + 1]


def _drag_rectangle_alignment(question: np.ndarray, answer: np.ndarray,
                              sources: list, destinations: list, answers: list) -> list | None:

    ordered = sorted(answers, key=lambda r: r[1])
    if len(ordered) != len(destinations):
        return None
    scales = [a[2] / d[2] for a, d in zip(ordered, destinations)]
    scale = float(np.median(scales))
    if scale <= 0 or max(abs(s / scale - 1) for s in scales) > .08:
        return None
    dx = float(np.median([a[0] - d[0] * scale for a, d in zip(ordered, destinations)]))
    dy = float(np.median([a[1] - d[1] * scale for a, d in zip(ordered, destinations)]))
    for a, d in zip(ordered, destinations):
        if (abs(a[0] - (d[0] * scale + dx)) > a[2] * .1
                or abs(a[1] - (d[1] * scale + dy)) > a[3] * .2
                or not .8 <= a[3] / (d[3] * scale) <= 1.2):
            return None
    transform = np.float32([[scale, 0, dx], [0, scale, dy]])
    height, width = answer.shape
    aligned = cv2.warpAffine(question, transform, (width, height), borderValue=255)
    mask = cv2.warpAffine(np.ones(question.shape, np.uint8), transform, (width, height),
                          flags=cv2.INTER_NEAREST)
    for x, y, w, h in ordered:
        cv2.rectangle(mask, (x-5, y-5), (x+w+5, y+h+5), 0, -1)
    for x, y, w, h in sources:
        cv2.rectangle(mask, (int(x*scale+dx)-3, int(y*scale+dy)-3),
                      (int((x+w)*scale+dx)+3, int((y+h)*scale+dy)+3), 0, -1)
    original = (aligned < 140) & (mask > 0)
    observed = (answer < 140) & (mask > 0)
    if original.sum() < 100 or observed.sum() < 100:
        return None
    kernel = np.ones((3, 3), np.uint8)
    near_original = cv2.dilate(original.astype(np.uint8), kernel) > 0
    near_observed = cv2.dilate(observed.astype(np.uint8), kernel) > 0
    if ((observed & near_original).sum() / observed.sum() < .72
            or (original & near_observed).sum() / original.sum() < .72):
        return None
    return ordered


def drag_match(question_image: bytes, answer_image: bytes) -> dict | None:

    try:
        q = _gray(question_image)
        a = _gray(answer_image)
    except (OSError, ValueError):
        return None
    for threshold in (200, 220):
        result = _drag_match_threshold(q, a, threshold)
        if result is not None:
            return result
    return None


def _drag_match_threshold(q: np.ndarray, a: np.ndarray, threshold: int) -> dict | None:
    candidates = _drag_rectangles(q, threshold)
    if len(candidates) < 4:
        return None
    left = min(r[0] for r in candidates)
    sources = sorted((r for r in candidates if abs(r[0] - left) <= q.shape[1] * .03),
                     key=lambda r: r[1])
    destinations = sorted((r for r in candidates if r not in sources), key=lambda r: r[1])
    if not (2 <= len(sources) <= 12 and 2 <= len(destinations) <= 8):
        return None
    widths = [r[2] for r in sources]
    heights = [r[3] for r in sources]
    if max(widths) > min(widths) * 1.15 or max(heights) > min(heights) * 1.2:
        return None
    if any(x <= left + max(widths) or not (.85 <= w / np.median(widths) <= 1.15)
           or not (.8 <= h / np.median(heights) <= 1.2)
           for x, y, w, h in destinations):
        return None
    source_text = [_drag_text(q, r) for r in sources]
    if any(t is None for t in source_text) or any(_drag_text(q, r) is not None for r in destinations):
        return None


    answers = _drag_rectangles(a, threshold)
    aligned = _drag_rectangle_alignment(q, a, sources, destinations, answers)
    matrix = _homography(q, a) if aligned is None else None
    if aligned is None and matrix is None:
        return None
    pairs = []
    used = set()
    for target_index, (x, y, w, h) in enumerate(destinations):
        if aligned is not None:
            answer_text = _drag_text(a, aligned[target_index])
        else:
            points = np.float32([[[x, y], [x + w, y + h]]])
            mapped = cv2.perspectiveTransform(points, matrix)[0]
            if not np.isfinite(mapped).all():
                return None
            x0, y0 = mapped[0]
            x1, y1 = mapped[1]
            if not (0 <= x0 < x1 <= a.shape[1] and 0 <= y0 < y1 <= a.shape[0]):
                return None
            matches = []
            for i, (ax, ay, aw, ah) in enumerate(answers):
                dx = abs((ax + aw / 2) - (x0 + x1) / 2) / (x1 - x0)
                dy = abs((ay + ah / 2) - (y0 + y1) / 2) / (y1 - y0)
                if dx < .3 and dy < .3 and .65 < aw / (x1-x0) < 1.4 and .65 < ah / (y1-y0) < 1.4:
                    matches.append(i)
            if len(matches) != 1 or matches[0] in used:
                return None
            used.add(matches[0])
            answer_text = _drag_text(a, answers[matches[0]])
        if answer_text is None:
            return None
        answer_norm = cv2.resize(answer_text, (180, 40), interpolation=cv2.INTER_AREA).astype(np.float32) / 255
        scores = []
        for text in source_text:
            original = cv2.resize(text, (180, 40), interpolation=cv2.INTER_AREA).astype(np.float32) / 255
            corr = float(np.corrcoef(original.ravel(), answer_norm.ravel())[0, 1])
            error = float(np.mean((original - answer_norm) ** 2))
            if not np.isfinite(corr):
                return None
            scores.append((corr, error))
        ranking = sorted(range(len(scores)), key=lambda i: scores[i][0], reverse=True)
        best, second = ranking[:2]
        correlation, error = scores[best]
        margin = correlation - scores[second][0]
        errors = sorted(score[1] for score in scores)


        confident = ((correlation >= .55 and margin >= .15)
                     or (correlation >= .50 and margin >= .25 and errors[1] - errors[0] >= .07))
        if not confident or min(range(len(scores)), key=lambda i: scores[i][1]) != best:
            return None
        pairs.append(best)
    objects = [(kind, 0, x, y, x + w, y + h)
               for kind, rects in ((1, sources), (2, destinations)) for x, y, w, h in rects]
    return {'objects': objects, 'targets': list(range(len(sources))) + pairs}


def combine_images(images: list[bytes]) -> bytes:

    converted = [Image.open(io.BytesIO(data)).convert('RGB') for data in images]
    width = max(im.width for im in converted)
    canvas = Image.new('RGB', (width, sum(im.height for im in converted)), 'white')
    y = 0
    for image in converted:
        canvas.paste(image, (0, y))
        y += image.height
    buffer = io.BytesIO()
    canvas.save(buffer, format='JPEG', quality=95, progressive=False)
    return buffer.getvalue()


def choice_with_image_options(question_images: list[bytes], options: list[str], option_images: list[list[bytes]]) -> dict | None:

    if len(options) != len(option_images) or any(not text.strip() and not images
                                                  for text, images in zip(options, option_images)):
        return None
    try:
        exhibits = [Image.open(io.BytesIO(data)).convert('RGB') for data in question_images]
        choices = [[Image.open(io.BytesIO(data)).convert('RGB') for data in group] for group in option_images]
    except (OSError, ValueError):
        return None
    width = max([600] + [im.width+20 for im in exhibits] + [im.width+20 for group in choices for im in group])
    font = ImageFont.load_default(size=23)
    probe = ImageDraw.Draw(Image.new('RGB', (1, 1)))
    lines_by_option = []
    for i, text in enumerate(options):
        lines = []
        line = f'{chr(65+i)}.'
        for word in text.split():
            candidate = line + ' ' + word
            if probe.textlength(candidate, font=font) > width-28:
                lines.append(line)
                line = word
            else:
                line = candidate
            if probe.textlength(line, font=font) > width-28:
                return None
        lines.append(line)
        lines_by_option.append(lines)
    height = (sum(im.height+10 for im in exhibits)
              + sum(len(lines)*30+10+sum(im.height+10 for im in group)
                    for lines, group in zip(lines_by_option, choices)) + 20)
    canvas = Image.new('RGB', (width, height), 'white')
    draw = ImageDraw.Draw(canvas)
    y = 10
    for im in exhibits:
        canvas.paste(im, (10, y))
        y += im.height+10
    rects = []
    for lines, group in zip(lines_by_option, choices):
        start = y
        for line in lines:
            draw.text((10, y), line, fill='black', font=font)
            y += 30
        y += 10
        for im in group:
            canvas.paste(im, (10, y))
            y += im.height+10
        rects.append((0, start, width, y-2))
    buffer = io.BytesIO()
    canvas.save(buffer, format='JPEG', quality=95, progressive=False)
    return {'image': buffer.getvalue(), 'rects': rects}


def choice_with_exhibit(image: bytes, options: list[str]) -> dict | None:

    try:
        base = Image.open(io.BytesIO(image)).convert('RGB')
    except Exception:
        return None
    width = max(base.width, 600)
    font = ImageFont.load_default(size=23)
    measure = ImageDraw.Draw(base)
    lines_by_option = []
    for index, option in enumerate(options):
        lines = []
        line = f'{chr(65 + index)}.'
        for word in option.split():
            candidate = line + ' ' + word
            if measure.textlength(candidate, font=font) > width-28 and line:
                lines.append(line)
                line = word
            else:
                line = candidate
        if measure.textlength(line, font=font) > width-28:
            return None
        lines.append(line)
        lines_by_option.append(lines)
    heights = [max(44, len(lines)*30+12) for lines in lines_by_option]
    canvas = Image.new('RGB', (width, base.height + sum(heights) + 24), 'white')
    canvas.paste(base, (0, 0))
    draw = ImageDraw.Draw(canvas)
    rects = []
    y = base.height + 10
    for lines, height in zip(lines_by_option, heights):
        for line in lines:
            if draw.textlength(line, font=font) > width-28:
                return None
        draw.multiline_text((14, y), '\n'.join(lines), fill='black', font=font, spacing=7)
        rects.append((10, y-4, width-10, y+height-4))
        y += height
    buffer = io.BytesIO()
    canvas.save(buffer, format='JPEG', quality=95)
    return {'image': buffer.getvalue(), 'rects': rects}


def image_size(image: bytes) -> tuple[int, int]:

    pil = Image.open(io.BytesIO(image))
    return pil.size


def jpeg_bytes(image: bytes) -> bytes:

    pil = Image.open(io.BytesIO(image))
    pil.load()
    if pil.format == 'JPEG' and not pil.info.get('progressive'):
        return image
    buffer = io.BytesIO()
    pil.convert('RGB').save(buffer, format='JPEG', quality=95, progressive=False)
    return buffer.getvalue()
