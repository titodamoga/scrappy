from __future__ import annotations

import struct
from datetime import datetime

RICH_PREFIX = b'-8 1 2\r\n0 1 0 8 0 0\r\n'
HOT_HEADER = b'\x09\xff\xff\xff\xff\x05\x00\x00\x00\x00\x00\x00\x00'
DRAG_HEADER = b'\x02\xff\xff\xff\xff\x05\x00\x00\x00\x00\x00\x00\x00'


class VceError(ValueError):
    pass


def xor_bytes(data: bytes) -> bytes:
    return bytes(c ^ (i & 255) for i, c in enumerate(data))


def xstr(data: bytes) -> bytes:
    return struct.pack('<I', len(data)) + xor_bytes(data)


def rich(text: str) -> bytes:

    body = RICH_PREFIX + text.replace('\n', '\r\n').encode('utf-16-le') + b') '
    return struct.pack('<I', len(body)) + body


def _question_text(fields: list[str]) -> bytes:
    return xstr(b''.join(rich(f) for f in fields))


def _header(code: str, title: str) -> bytes:

    try:
        coded = code.encode('ascii')
        titled = title.encode('ascii')
    except UnicodeEncodeError as exc:
        raise VceError('El código y el título del examen deben ser ASCII.') from exc


    now = datetime.now()
    day = (now.date() - datetime(1899, 12, 30).date()).days
    fraction = (now.hour * 3600 + now.minute * 60 + now.second + now.microsecond / 1e6) / 86400
    header = bytearray(b'\x85\xa8\x01\x01\x00')
    header += xstr(coded) + xstr(titled)
    header += struct.pack('<II', 800, 120)
    header += xstr(b'1.0')
    header += struct.pack('<4d', day, fraction, day, fraction)
    header += bytes(6)
    header += xstr(bytes(8)) + xstr(rich(''))
    header += b'\x00\x00\x00\x00\x01\x00\x00\x00\x00'
    return bytes(header)


def choice_record(question: dict) -> bytes:
    options = question['options']
    answer = question['answer']
    number = len(options)
    fields = [question['question'], *options, question.get('explanation', '')]

    body = bytes([0 if len(answer) == 1 else 1]) + b'\xff\xff\xff\xff\x05\x00\x00\x00\x00\x00\x00\x00'
    body += _question_text(fields)
    body += xstr(answer.encode('ascii'))
    body += struct.pack('<I', number) + b'\x01\x00\x00'
    body += xstr(b'')
    return body


def hot_record(question: dict) -> bytes:
    rects = question['rects']
    correct = question['correct']
    coords = struct.pack('<I', len(rects)) + b''.join(struct.pack('<4i', *r) for r in rects)
    marks = struct.pack('<I', len(rects)) + bytes(1 if i in correct else 0 for i in range(len(rects)))
    text = _question_text([question['question'], question.get('explanation', '')])
    return (HOT_HEADER + xstr(coords) + xstr(marks) + text + b'\x02\x00'
            + xstr(question['image']))


def drag_record(question: dict) -> bytes:
    objects = question['objects']
    targets = question['targets']
    coords = struct.pack('<I', len(objects)) + b''.join(struct.pack('<iBiiii', *o) for o in objects)
    marks = struct.pack('<I', len(objects)) + struct.pack('<' + 'i' * len(objects), *targets)
    text = _question_text([question['question'], question.get('explanation', '')])
    mode = b'\x02\x01' if question.get('reuse') else b'\x02\x00'
    return (DRAG_HEADER + xstr(coords) + xstr(marks) + text + mode
            + xstr(question['image']))


def blank_record(number: int, reason: str, question: str = '', options: list[str] | None = None,
                 labels: list[str] | None = None) -> bytes:

    text = question or f'[PREGUNTA {number} NO CONVERTIDA]'
    options = options or []
    if labels and labels != [chr(65+i) for i in range(len(options))]:
        text += '\n' + '\n'.join(f'{labels[i] if i < len(labels) else "?"}. {option}'
                                  for i, option in enumerate(options))

    if len(options) < 2:
        options = [*options, *(['Sin respuesta reconocida'] * (2-len(options)))]
    return choice_record({'question': text, 'options': options, 'answer': '',
                          'explanation': 'PREGUNTA NO DETECTADA CORRECTAMENTE\n' + reason})


def build(records: list[bytes], code: str, title: str) -> bytes:

    output = bytearray(_header(code, title))
    output += struct.pack('<I', len(records))
    for record in records:
        output += record
    output += struct.pack('<I', len(output))
    return bytes(output)
