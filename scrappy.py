from __future__ import annotations

import os
import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
VENDOR = Path(os.environ['SCRAPPY_VENDOR']).expanduser().resolve() if os.environ.get('SCRAPPY_VENDOR') else BASE / 'vendor'

EXPECTED = {'pymupdf': '1.28.2', 'PIL': '13.0.0', 'numpy': '2.5.5',
            'cv2': '5.0.0', 'built_with': '3.15'}


def _bootstrap() -> None:

    if not VENDOR.is_dir():
        print(f'ERROR: no existe la carpeta de dependencias: {VENDOR}')
        print('Ejecuta SCRAPPY.BAT o revisa SCRAPPY_VENDOR y el README.')
        raise SystemExit(1)
    sys.path.insert(0, str(VENDOR))
    problems = []
    for name in ('pymupdf', 'PIL', 'numpy', 'cv2'):
        try:
            module = __import__(name)
        except Exception as exc:
            problems.append(f'{name}: {exc}')
            continue
        expected = EXPECTED.get(name)
        actual = getattr(module, '__version__', None)
        if expected and actual and not str(actual).startswith(expected):
            problems.append(f'{name}: version {actual} distinta de {expected}')
        origin = Path(getattr(module, '__file__', '') or '').resolve()
        if VENDOR.resolve() not in origin.parents:
            problems.append(f'{name}: se carga desde {origin}, no desde {VENDOR}')
    if problems:
        print('ERROR: las dependencias incluidas no se pueden usar:')
        for problem in problems:
            print('  -', problem)
        print()
        print('Python en uso:', sys.version.split()[0])
        print('Para el Python integrado, ejecuta SCRAPPY.BAT y restaura vendor si falta.')
        print('Para un Python propio, revisa SCRAPPY_VENDOR y los pasos del README.')
        raise SystemExit(1)


_bootstrap()

import graphics
import pdf_reader
import vce_writer

INGESTA = BASE / 'INGESTA'
ENTREGA = BASE / 'ENTREGA'
EXAM_CODE = re.compile(r'\b([A-Z]{2,3}-\d{3})\b')
CHOICE_COUNT = re.compile(r'\b(?:choose|select)\s+(one|two|three|four|five|six|seven|eight|[1-8])\b', re.I)
CHOICE_NUMBERS = {'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5, 'six': 6, 'seven': 7, 'eight': 8}


class Log:


    def __init__(self, path: Path):
        self.path = path
        self.lines: list[str] = []

    def __call__(self, message: str = '') -> None:
        print(message, flush=True)
        self.lines.append(message)

    def save(self) -> None:
        self.path.write_text('\n'.join(self.lines) + '\n', encoding='utf-8')


def exam_code(pdf_path: Path, questions: list[pdf_reader.Question]) -> str:
    text = ' '.join(' '.join(q.prompt) for q in questions[:3])
    found = EXAM_CODE.search(text)
    if found:
        return found.group(1)
    import re
    code = re.sub(r'[^A-Z0-9_-]', '', pdf_path.stem.split('-')[0].upper())
    return code or 'EXAM'


def convert_question(question: pdf_reader.Question, number: int) -> tuple[str, bytes | None, str]:

    explanation = 'Creado con Scrappy'
    if question.kind == 'choice':
        if not question.answer or len(question.options) < 2:
            return 'sin respuesta', None, 'opciones o respuesta no reconocidas'
        expected_labels = [chr(65 + i) for i in range(len(question.options))]
        if (question.option_labels and question.option_labels != expected_labels) or (any(not o.strip() for o in question.options) and not question.option_images):
            return 'blanca', None, 'alternativas incompletas, desordenadas o sin texto'
        letters = set(question.answer)
        if len(letters) != len(question.answer) or any(ord(letter) - 65 >= len(question.options) for letter in letters):
            return 'blanca', None, 'respuesta ambigua o fuera del rango de opciones'
        counts = {CHOICE_NUMBERS[value.lower()] if not value.isdigit() else int(value)
                  for value in CHOICE_COUNT.findall(question.text)}
        if counts and counts != {len(letters)}:
            return 'blanca', None, 'respuesta incompatible con el numero de opciones solicitadas'
        if question.images:
            if question.option_images:
                option_ids = {id(image) for group in question.option_image_blocks for image in group}
                exhibit = graphics.choice_with_image_options(
                    [image.data for image in question.images if id(image) not in option_ids],
                    question.options, [[image.data for image in group] for group in question.option_image_blocks])
            else:
                exhibit = graphics.choice_with_exhibit(
                    graphics.combine_images([item.data for item in question.images]), question.options)
            if exhibit is None:
                return 'blanca', None, 'no se pudo preparar la imagen del enunciado'
            record = vce_writer.hot_record({
                'question': question.text,
                'rects': exhibit['rects'],
                'correct': sorted(ord(letter) - 65 for letter in letters),
                'image': exhibit['image'],
                'explanation': explanation,
            })
            return 'hotspot (imagen)', record, ''
        record = vce_writer.choice_record({
            'question': question.text,
            'options': question.options,
            'answer': question.answer,
            'explanation': explanation,
        })
        return 'opcion', record, ''
    if question.kind == 'hotspot':
        if len(question.images) < 2:
            return 'blanca', None, 'faltan las imágenes de enunciado y respuesta'
        question_image = question.images[0].data
        answer_image = question.images[1].data

        detected = graphics.hotspot_grid(question_image, answer_image)
        stage = 'rejilla'
        if detected is None:
            detected = graphics.hotspot_marks(question_image, answer_image)
            stage = 'marca'
        if detected is None:
            detected = graphics.hotspot_marks(question_image, answer_image, iterations=2)
            stage = 'marca fina'
        if detected is None:
            detected = graphics.hotspot_grid_norm(question_image, answer_image)
            stage = 'rejilla normalizada'
        if detected is None:
            return 'sin detectar', None, 'no se reconocieron las zonas o las marcas'
        if stage in ('marca', 'marca fina'):


            marks = detected
            detected = graphics.hotspot_complete_grid(question_image, marks)
            stage = 'rejilla por marcas'
            if detected is None:
                detected = graphics.hotspot_dropdown(question_image, marks)
                stage = 'desplegable'
            if detected is None:
                return 'sin detectar', None, 'no se reconocieron todas las alternativas'
        record = vce_writer.hot_record({
            'question': question.text,
            'rects': detected['rects'],
            'correct': detected['correct'],
            'image': graphics.jpeg_bytes(question_image),
            'explanation': explanation,
        })
        return f'hotspot ({stage})', record, ''
    if question.kind == 'drag':
        if len(question.images) < 2:
            return 'sin detectar', None, 'faltan imágenes del enunciado o respuesta'


        text = ' '.join(question.text.lower().split())
        if 'more than once' in text:
            reuse = True
        elif 'only once' in text:
            reuse = False
        else:
            return 'sin detectar', None, 'modalidad de reutilización no reconocida'
        detected = graphics.drag_match(question.images[0].data, question.images[1].data)
        if detected is None:
            return 'sin detectar', None, 'casillas o correspondencias no reconocidas con seguridad'
        if not reuse:
            source_count = sum(obj[0] == 1 for obj in detected['objects'])
            assigned = detected['targets'][source_count:]
            if len(set(assigned)) != len(assigned):
                return 'sin detectar', None, 'respuesta incompatible con uso único'
        record = vce_writer.drag_record({
            'question': question.text, **detected, 'reuse': reuse,
            'image': graphics.jpeg_bytes(question.images[0].data),
            'explanation': explanation,
        })
        return 'arrastrar', record, ''
    return 'blanca', None, question.reason or 'tipo de pregunta no reconocido'


def image_fallback(question: pdf_reader.Question, reason: str) -> bytes | None:

    if not question.images:
        return None
    try:
        image = graphics.combine_images([item.data for item in question.images])
        width, height = graphics.image_size(image)
    except (OSError, ValueError):
        return None
    text = question.text
    if question.options:
        text += '\n' + '\n'.join(f'{question.option_labels[i] if i < len(question.option_labels) else chr(65+i)}. {option}'
                                  for i, option in enumerate(question.options))
    return vce_writer.hot_record({
        'question': text,
        'rects': [(0, 0, width, height)],
        'correct': [],
        'image': image,
        'explanation': ('PREGUNTA NO DETECTADA CORRECTAMENTE\n'
                        f'{reason}. Revisa el PDF original y su respuesta.'),
    })


def unique_path(folder: Path, stem: str, suffix: str) -> Path:
    candidate = folder / f'{stem}{suffix}'
    counter = 2
    while candidate.exists():
        candidate = folder / f'{stem}_{counter}{suffix}'
        counter += 1
    return candidate


def main() -> int:
    for folder in (INGESTA, ENTREGA):
        folder.mkdir(exist_ok=True)
    from datetime import datetime
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    log = Log(unique_path(ENTREGA, f'scrappy-{stamp}', '.txt'))
    log(f'Scrappy - {datetime.now():%d/%m/%Y %H:%M}')
    log(f'Entrada: {INGESTA}')
    log(f'Salida:  {ENTREGA}')
    log()

    pdfs = sorted(p for p in INGESTA.iterdir() if p.suffix.lower() == '.pdf')
    if not pdfs:
        log('ERROR: no hay archivos PDF en INGESTA.')
        log.save()
        return 1
    totals = {'convertidas': 0, 'imagenes': 0, 'blancas': 0, 'archivos': 0, 'fallidos': 0}
    all_records: list[bytes] = []
    answer_code = ''

    for pdf_path in pdfs:
        log('=' * 72)
        log(f'ARCHIVO: {pdf_path.name}')
        try:
            questions = pdf_reader.read_pdf(pdf_path)
        except Exception as exc:
            totals['fallidos'] += 1
            log(f'  NO CONVERTIDO: formato no entendido ({exc})')
            continue
        records, converted, images, blank = [], 0, [], []
        for question in questions:
            number = len(all_records) + len(records) + 1
            kind, record, reason = convert_question(question, number)
            if record is None:
                record = image_fallback(question, reason)
                if record is not None:
                    kind = 'imagen con aviso'
                    images.append(question.number)
                else:
                    kind = 'texto con aviso'
                    blank.append((question.number, reason))
                    record = vce_writer.blank_record(number, reason, question.text, question.options, question.option_labels)
            else:
                converted += 1
            records.append(record)
            log(f'  P{question.number:<4} {question.kind:<8} -> {kind}'
                + (f'  [{reason}]' if reason else ''))
        code = exam_code(pdf_path, questions)
        answer_code = answer_code or code
        all_records.extend(records)
        totals['archivos'] += 1
        totals['convertidas'] += converted
        totals['imagenes'] += len(images)
        totals['blancas'] += len(blank)
        log(f'  RESULTADO: {converted} convertidas, {len(images)} con imagen y aviso, '
            f'{len(blank)} con texto y aviso de {len(questions)}')
        if images:
            log('  Con imagen y aviso: ' + ', '.join(str(n) for n in images))
        if blank:
            log('  Con texto y aviso: ' + ', '.join(str(n) for n, _r in blank))


    if not all_records:
        log('ERROR: no se encontró ninguna pregunta; no se generó un VCE.')
        log.save()
        return 1

    data = vce_writer.build(all_records, answer_code or 'EXAM', f'{answer_code or "EXAM"} Scrappy')
    output = unique_path(ENTREGA, 'Scrappy', '.vce')
    written = False
    try:
        with output.open('xb') as handle:
            handle.write(data)
        written = True
    except OSError as exc:
        totals['fallidos'] += 1
        log(f'  ERROR al escribir {output.name}: {exc}')

    log()
    log('=' * 72)
    log('RESUMEN')
    log(f'  Archivos leidos:       {totals["archivos"]}')
    log(f'  Archivos fallidos:     {totals["fallidos"]}')
    log(f'  Preguntas en el VCE:   {len(all_records)}')
    log(f'  Preguntas convertidas: {totals["convertidas"]}')
    log(f'  Imágenes con aviso:    {totals["imagenes"]}')
    log(f'  Textos con aviso:      {totals["blancas"]}')
    log(f'  VCE generado:          {output.name if written else "no generado"}')
    log(f'  Registro:              {log.path.name}')
    log.save()
    return 1 if totals['fallidos'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
