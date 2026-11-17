from __future__ import annotations

import io
import re
from dataclasses import dataclass, field

import pymupdf
from PIL import Image


QUESTION_HEADER = re.compile(r'^[ \t]*Question[ \t]*#[ \t]*(\d+)[ \t]*(?=\(Topic[ \t]*:|$)', re.I | re.M)
TOPIC_HEADER = re.compile(r'^\s*\(Topic\s*:', re.I)
OPTION_LINE = re.compile(r'^\s*([A-H])\.\s*(.*)$')
ANSWER = re.compile(r'^Correct Answer\s*:\s*(.*?)\s*$', re.I)
NOISE = re.compile(r'^\s*(Topic\s*\d+|Exam\s+[A-Z]|Most Voted|Reveal (?:Solution|Answer)|\))\s*$', re.I)
BOILERPLATE = re.compile(r'(You have\s+Contributor Access.*|Browse at least 50%.*|'
                         r'Viewing (page|questions).*|Previous Questions|Next Questions|'
                         r'\d+\s+questions\s*$|Browse\s+at\s*least\s+50%.*|'
                         r'.*ExamTopics\s*$|https?://www\.examtopics\.com/|'
                         r'\d+\s+(?:de|of)\s+\d+\s*$|\d{1,2}/\d{1,2}/\d{4},\s*\d{1,2}:\d{2}\s*$)', re.I)


@dataclass
class ImageBlock:
    data: bytes
    ext: str
    width: int
    height: int
    page: int
    y: float
    bbox: tuple[float, ...] | None = None
    transform: tuple[float, ...] | None = None


@dataclass
class Question:
    number: int
    kind: str = 'unknown'
    prompt: list[str] = field(default_factory=list)
    options: list[str] = field(default_factory=list)
    answer: str = ''
    images: list[ImageBlock] = field(default_factory=list)
    reason: str = ''
    option_labels: list[str] = field(default_factory=list)
    option_images: bool = False
    option_image_blocks: list[list[ImageBlock]] = field(default_factory=list)

    @property
    def text(self) -> str:
        return '\n'.join(line for line in self.prompt if line.strip()).strip()


def _ordered_blocks(page: pymupdf.Page):
    for block in page.get_text('dict')['blocks']:
        if block['type'] == 0:
            lines = []
            for line in block['lines']:
                text = ''.join(span['text'] for span in line['spans'])
                if text.strip():
                    lines.append(text.rstrip())
            if lines:
                yield ('text', block['bbox'][1], '\n'.join(lines))
        elif block['type'] == 1 and block.get('image'):
            yield ('image', block['bbox'][1], block)


def _as_image(block, page, y):
    return ImageBlock(data=block['image'], ext=block['ext'], width=block['width'],
                      height=block['height'], page=page, y=y,
                      bbox=block.get('bbox'), transform=block.get('transform'))


def _continued_image(previous: ImageBlock, image: ImageBlock) -> bool:

    if (image.page != previous.page + 1 or previous.data != image.data
            or not previous.bbox or not image.bbox
            or not previous.transform or not image.transform):
        return False
    a, b = previous.transform, image.transform
    if (any(abs(a[i] - b[i]) > .1 for i in (0, 1, 2, 3, 4))
            or abs(a[1]) > .1 or abs(a[2]) > .1 or a[0] <= 0 or a[3] <= 0):
        return False


    first_start = (previous.bbox[1] - a[5]) / a[3]
    first_end = (previous.bbox[3] - a[5]) / a[3]
    second_start = (image.bbox[1] - b[5]) / b[3]
    second_end = (image.bbox[3] - b[5]) / b[3]
    return (abs(first_start) < .005 and abs(second_end - 1) < .005
            and .005 < first_end < .995 and abs(first_end - second_start) < .005)


def _answer_letters(line: str) -> str:

    match = ANSWER.match(line)
    if not match:
        return ''
    text = re.split(r'\s+Community vote\b', match.group(1), maxsplit=1, flags=re.I)[0]
    text = re.sub(r'\band\b', ',', text.strip(), flags=re.I)
    if not re.fullmatch(r'[A-H](?:[\s,;/+&]*[A-H])*\.?', text, re.I):
        return ''
    return ''.join(re.findall(r'[A-H]', text.upper()))


def _card_images(page):

    blocks = [b for b in page.get_text('dict')['blocks'] if b['type'] == 1]
    headers = [b for b in blocks if b['width'] > 4000 and 180 <= b['height'] <= 250
               and b['bbox'][2] - b['bbox'][0] > page.rect.width * .8]
    cards = []
    for b in blocks:
        x0, y0, x1, y1 = b['bbox']
        if x1-x0 < page.rect.width*.8 or y1-y0 < 40:
            continue
        if any(h is not b and abs(h['bbox'][1]-y0) < 2 for h in headers):
            cards.append(pymupdf.Rect(b['bbox']))
    return sorted(cards, key=lambda r: r.y0), blocks


def _raster_question(parts, number):

    images = [Image.open(io.BytesIO(data)).convert('RGB') for data in parts]
    width = max(image.width for image in images)
    canvas = Image.new('RGB', (width, sum(im.height for im in images)), 'white')
    y = 0
    for image in images:
        canvas.paste(image, (0, y))
        y += image.height
    out = io.BytesIO()
    canvas.save(out, format='JPEG', quality=92)
    return Question(number=number, kind='imagen',
                    prompt=['Pregunta escaneada: consulta el contenido de la imagen.'],
                    images=[ImageBlock(out.getvalue(), 'jpeg', canvas.width, canvas.height, 0, 0)],
                    reason='PDF basado en imágenes; respuesta no interpretada')


def _read_image_pdf(document):

    parts = []
    pending_at_bottom = False
    questions = []
    saw_cards = False
    for page in document:
        cards, blocks = _card_images(page)
        if cards:
            saw_cards = True


        top = cards[0].y0 if cards else page.rect.height
        continuation = [b for b in blocks if b['bbox'][1] < top-2 and b['bbox'][3] > 5]
        if parts and pending_at_bottom and continuation:
            x0 = min(b['bbox'][0] for b in continuation)
            x1 = max(b['bbox'][2] for b in continuation)
            bottom = min(top, max(b['bbox'][3] for b in continuation))
            clip = pymupdf.Rect(max(0, x0-2), 0, min(page.rect.width, x1+2), bottom)
            parts.append(page.get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5), clip=clip, alpha=False).tobytes('png'))
            pending_at_bottom = bottom >= page.rect.height-25
        for card in cards:
            if parts:
                questions.append(_raster_question(parts, len(questions)+1))
            clip = pymupdf.Rect(max(0, card.x0-2), max(0, card.y0-2),
                                min(page.rect.width, card.x1+2), min(page.rect.height, card.y1+2))
            parts = [page.get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5), clip=clip, alpha=False).tobytes('png')]
            pending_at_bottom = card.y1 >= page.rect.height-25
    if parts:
        questions.append(_raster_question(parts, len(questions)+1))
    if saw_cards:
        return questions


    for page in document:
        for b in page.get_text('dict')['blocks']:
            if (b['type'] == 1 and b.get('image') and b['width'] >= 300 and b['height'] >= 100
                    and b['bbox'][2]-b['bbox'][0] >= page.rect.width*.4):
                questions.append(_raster_question([b['image']], len(questions)+1))
    return questions


def read_pdf(path) -> list[Question]:
    try:
        document = pymupdf.open(path)
    except Exception as exc:
        raise ValueError(f'No se pudo abrir el PDF: {exc}') from exc
    try:
        questions: list[Question] = []
        current: Question | None = None
        after_answer = False
        in_topic = False
        for page_number, page in enumerate(document, start=1):
            for kind, y, payload in _ordered_blocks(page):
                if kind == 'image':
                    if current is not None and (not after_answer or current.kind in ('hotspot', 'drag')):
                        image = _as_image(payload, page_number, y)
                        if current.images and _continued_image(current.images[-1], image):
                            continue
                        current.images.append(image)
                        if current.options and not after_answer:
                            current.option_images = True
                            current.option_image_blocks[-1].append(image)
                    continue
                for line in payload.split('\n'):
                    header = QUESTION_HEADER.match(line)
                    if header:
                        if current is not None:
                            questions.append(current)
                        current = Question(number=int(header.group(1)))
                        line = line[header.end():]
                        after_answer = False
                        in_topic = False
                    elif current is None:
                        continue
                    stripped = line.strip()
                    if in_topic:
                        if ')' in stripped:
                            stripped = stripped.split(')', 1)[1].strip()
                            in_topic = False
                        else:
                            continue
                    if TOPIC_HEADER.match(stripped):
                        if ')' in stripped:
                            stripped = stripped.split(')', 1)[1].strip()
                        else:
                            in_topic = True
                            continue
                    if not stripped or NOISE.match(stripped) or BOILERPLATE.match(stripped):
                        continue
                    if re.fullmatch(r'HOT\s*SPOT\s*[-:]?', stripped, re.I):
                        current.kind = 'hotspot'
                        continue
                    if re.fullmatch(r'DRAG\s*[- ]?\s*DROP\s*[-:]?', stripped, re.I):
                        current.kind = 'drag'
                        continue
                    if re.match(r'Correct Answer\s*:', stripped, re.I):
                        after_answer = True
                        current.answer = _answer_letters(stripped)
                        continue
                    if after_answer:
                        continue
                    option = OPTION_LINE.match(stripped)
                    if option and current.kind not in ('hotspot', 'drag'):
                        value = re.split(r'\s{2,}Most Voted', option.group(2))[0].strip()
                        current.options.append(value)
                        current.option_image_blocks.append([])
                        current.option_labels.append(option.group(1))
                        if current.kind == 'unknown':
                            current.kind = 'choice'
                    elif current.options:
                        current.options[-1] = (current.options[-1] + ' ' + stripped).strip()
                    else:
                        current.prompt.append(stripped)
        if current is not None:
            questions.append(current)
        if questions:
            return questions
        if any(re.search(r'\w{20}', page.get_text()) for page in document):
            raise ValueError('El PDF tiene texto, pero no contiene encabezados de pregunta reconocibles.')
        questions = _read_image_pdf(document)
        if not questions:
            raise ValueError('El PDF no contiene preguntas ni capturas reconocibles.')
        return questions
    finally:
        document.close()
