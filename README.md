# Scrappy

Convierte volcados PDF de **ExamTopics** en archivos **`.vce`** que se pueden abrir con VCE Designer y VCE Player.

El programa lee **todos los PDF de una carpeta** por orden alfabético, extrae las preguntas con sus opciones y respuestas, y genera **un único `.vce`** con todas ellas, conservando el orden y la numeración del conjunto.

---

## Requisitos

| Requisito | Detalle |
| --- | --- |
| Sistema | Windows x64 (64 bits) |
| Python | **CPython 3.15.0 integrado** en `python/`: no hace falta instalar Python |
| Dependencias | **Ninguna que instalar**: están incluidas en `vendor/` |
| Conexión a Internet | No es necesaria para el uso normal |

Ejecuta `SCRAPPY.BAT`: usa exclusivamente el intérprete incluido, sin alterar ni depender del Python del sistema. Conserva completas las carpetas `python/` y `vendor/`. No hace falta `pip` ni permisos de administrador para el uso normal. Algunas instalaciones de Windows pueden requerir componentes de ejecución de Microsoft adicionales.

### Versiones incluidas

| Biblioteca | Versión | Uso | Licencia |
| --- | --- | --- | --- |
| PyMuPDF | 1.28.2 | lectura de PDF | AGPL-3.0 |
| Pillow | 13.0.0 | tratamiento de imágenes | MIT-CMU |
| numpy | 2.5.5 | cálculo numérico | BSD-3-Clause |
| opencv-python-headless | 5.0.0.93 | detección de zonas | Apache-2.0 |

Las licencias completas están en `vendor/LICENCIAS/` y el detalle en `vendor/DEPENDENCIAS.txt`.

> Las bibliotecas incluidas están preparadas para el CPython 3.15 integrado en Windows x64. La licencia de Python se incluye en `python/LICENSE.txt`. Para usar otro intérprete, sigue los pasos de la sección siguiente.

---

## Uso

1. Copia los PDF de ExamTopics en la carpeta `INGESTA/`.
2. Ejecuta **`SCRAPPY.BAT`** (doble clic) o, desde una consola:
   ```
   python\python.exe scrappy.py
   ```
3. Recoge el archivo `ENTREGA/Scrappy.vce`. Es **uno solo**: contiene las preguntas de todos los PDF de `INGESTA`, unidas en el orden alfabético de los archivos.
4. Lee el registro: se muestra en pantalla y se guarda como `ENTREGA/scrappy-AAAAMMDD-HHMMSS.txt`.

El lanzador `.bat` utiliza el Python integrado mediante rutas relativas. Si falta, avisa: restaura la carpeta `python/` desde una copia completa de Scrappy.

Los archivos nunca se sobrescriben: si el destino ya existe, se añade `_2`, `_3`, etc.

### Usar tu propio Python (opcional)

`SCRAPPY.BAT` siempre usa el Python integrado. Si prefieres otro, necesitas **CPython de 64 bits en Windows**, `pip` y acceso a Internet para instalar las dependencias. Los metadatos de las versiones fijadas indican un mínimo de Python 3.12; como margen orientativo, prueba CPython 3.12 a 3.15 normal, no *free-threaded*. Fuera de ese rango, o sin ruedas compatibles, la instalación puede fallar. Esta alternativa no está validada en todas esas versiones.

Desde una consola en la carpeta `Scrappy`, sustituye `3.12` por la versión que vayas a usar y ejecuta:

```bat
py -3.12 -m pip install --only-binary=:all: --target .dependencias-python-propio -r requirements.txt
set "SCRAPPY_VENDOR=%CD%\.dependencias-python-propio"
py -3.12 scrappy.py
```

Repite la instalación en una carpeta distinta si cambias de versión de Python: Pillow y NumPy incluyen binarios específicos para cada versión. `SCRAPPY_VENDOR` indica dónde cargar las cuatro dependencias y solo afecta a la consola actual; no sustituye la carpeta `vendor/` del Python integrado. Usa la misma versión del intérprete para instalar y ejecutar, comprueba el resultado y no des por garantizada la compatibilidad. Para volver al uso normal, ejecuta `SCRAPPY.BAT`.

---

## Qué convierte

| Tipo de pregunta | Resultado |
| --- | --- |
| Opción única y múltiple | Convertida: enunciado, opciones y respuesta |
| Enunciado con imágenes | Convertida cuando se pueden dibujar todas las opciones completas como zonas seleccionables |
| Opciones con imágenes | Convertida cuando cada opción tiene sus imágenes y pueden conservarse completas |
| Áreas (*Hotspot*) en tablas Sí/No y desplegables | Convertidas cuando se reconocen todas las alternativas y las seleccionadas |
| Arrastrar y colocar (*Drag Drop*) | Se convierte cuando se reconocen con seguridad las casillas y sus correspondencias |
| PDF basados en capturas | Se intentan recuperar tarjetas o imágenes con aviso; no se reconoce automáticamente su texto ni su respuesta |
| Preguntas no reconocidas | Se conservan el enunciado, opciones e imágenes disponibles con el aviso `PREGUNTA NO DETECTADA CORRECTAMENTE`, sin respuesta correcta |

Las preguntas de área se analizan mediante rejillas y contornos de distintos grosores. Para los desplegables se intenta reconstruir la lista completa de opciones; para las tablas se identifican ambos botones de cada fila. Si no se pueden reconocer todas las alternativas, se conservan las imágenes disponibles con el aviso `PREGUNTA NO DETECTADA CORRECTAMENTE` en el comentario.

Para arrastrar y colocar se comprueban en secuencia las casillas del enunciado y la correspondencia visual de cada respuesta con las opciones. Si el diseño o la coincidencia resultan ambiguos, se conserva la imagen con un aviso en el comentario, sin marcar una respuesta como correcta. Estas preguntas se contabilizan por separado en el registro y deben revisarse con el PDF.

Las respuestas convertidas se copian de ExamTopics y no se verifican independientemente. Las explicaciones de esas preguntas dicen `Creado con Scrappy`. Si falta la respuesta revelada o es ambigua, se conserva la pregunta con aviso y sin respuesta marcada.

**Scrappy no realiza OCR**: lee la capa de texto que ya contiene el PDF y no reconoce letras dentro de capturas. Los PDF compuestos solo por imágenes (como ciertas exportaciones) no tienen texto extraíble. Scrappy intenta conservar cada tarjeta o captura, incluso sus fragmentos entre páginas, con aviso y sin solución interpretada. La separación es heurística: revisa las tarjetas y sus límites frente al PDF; no es OCR ni convierte esas respuestas en preguntas interactivas. Las capturas individuales de otros formatos también se conservan con aviso, pero no se garantiza que cada una contenga exactamente una pregunta. Los rangos solapados de distintos PDF no se eliminan y pueden producir preguntas repetidas.

---

## Estructura

```
Scrappy/
├── SCRAPPY.BAT               Lanzador del Python integrado
├── scrappy.py               Programa principal
├── pdf_reader.py            Lectura de preguntas, opciones y respuestas
├── graphics.py              Detección de zonas y normalización de imágenes
├── vce_writer.py            Escritura del formato VCE 1.1
├── INGESTA/                 PDF de entrada
├── ENTREGA/                 VCE y registros generados
├── python/                  CPython integrado para Windows x64 y licencia
├── vendor/                  Dependencias incluidas, con sus licencias
├── instalar_dependencias.bat  Reparación opcional con Python 3.15 x64 externo y pip
├── requirements.txt         Versiones exactas de las bibliotecas
├── LICENSE                  Licencia del código propio de Scrappy
└── LEEME.txt                Guía rápida en texto plano
```

---

## Detalles técnicos

Scrappy genera **VCE 1.1** sin leer ni necesitar un archivo VCE de partida. La cabecera y los registros se construyen en Python; no se dispone de una especificación oficial y la compatibilidad con otras versiones no está garantizada. Se usan como valores predeterminados 120 minutos y nota de corte 800, no verificados para el examen original.

Las imágenes se guardan siempre como **JPEG no progresivo**. Un PNG declarado como JPEG hace que Designer muestre el error `JPEG Error #53` al abrir la pregunta.

Para las tablas Sí/No, el programa localiza los botones de opción, calcula una homografía entre la imagen del enunciado y la de la respuesta, y considera marcadas las celdas que ganan tinta. Si la comprobación no es concluyente, la pregunta se deja en blanco.

---

## Formato VCE y licencia del reproductor

**`.vce` es un formato propietario.** Este proyecto solo escribe el archivo; no incluye ni sustituye al programa que lo abre. Para utilizarlo se necesita una versión licenciada de VCE Simulator / VCE Designer, que se adquiere en el sitio oficial de Avanset:

<https://www.avanset.com/vce-simulator.html>

Scrappy no está afiliado a Avanset ni a ExamTopics, y no distribuye, desbloquea ni modifica su software. Si no se dispone de licencia, el archivo generado no se podrá abrir. La ausencia de una plantilla no determina por sí sola los derechos sobre el formato o el contenido: consulta las condiciones aplicables y, si vas a distribuirlo, asesórate jurídicamente.

---

## Aviso sobre los contenidos

El contenido de los PDF pertenece a sus respectivos autores o titulares de derechos. La persona que utiliza Scrappy es responsable de contar con los permisos necesarios y de respetar las condiciones de uso y distribución aplicables. Scrappy no descarga contenido ni elude controles de acceso.

---

## Licencia y créditos

El código propio de Scrappy, creado por **DAMOGA** (David Morales García), se ofrece como código abierto bajo la licencia permisiva [0BSD](LICENSE): permite usarlo, modificarlo y distribuirlo para cualquier fin, también comercial. Se proporciona sin garantía. La idea puede utilizarse libremente.

Esta licencia no sustituye las de Python ni las de las bibliotecas incluidas. En particular, PyMuPDF se distribuye bajo AGPL-3.0 o licencia comercial; su uso y distribución pueden conllevar obligaciones propias. Consulta `python/LICENSE.txt`, `vendor/LICENCIAS/` y las condiciones de cada componente antes de distribuir el conjunto.
