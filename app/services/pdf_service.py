"""Pembuatan PDF rekap jurnal lengkap ACTRACE."""

import logging
from datetime import date, datetime
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

from PIL import Image as PILImage, ImageOps, UnidentifiedImageError

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, Image, KeepTogether, HRFlowable, Flowable, CondPageBreak,
)

logger = logging.getLogger(__name__)


# =============================================================================
# DESIGN TOKENS
# =============================================================================

NAVY = colors.HexColor("#142D4E")
TEAL = colors.HexColor("#0D9488")
LIGHT = colors.HexColor("#F3F5F7")
WHITE = colors.white
TEXT = colors.HexColor("#1F2937")
MUTED = colors.HexColor("#6B7280")
BORDER = colors.HexColor("#DDE2E8")
ERROR = colors.HexColor("#9F3434")

# Alias lama dipertahankan agar kompatibel dengan kode lain yang mungkin
# mengimpor nama warna dari modul ini.
CYAN = TEAL
BLUE = NAVY
PALE = LIGHT

PAGE_WIDTH, PAGE_HEIGHT = A4
MARGIN_X = 19 * mm
MARGIN_TOP = 23 * mm
MARGIN_BOTTOM = 20 * mm
USABLE_WIDTH = PAGE_WIDTH - 2 * MARGIN_X

BADGE_WIDTH = 13 * mm
PHOTO_GUTTER = 5 * mm
PHOTO_CELL_PAD = 5          # points
PHOTO_MAX_HEIGHT = 58 * mm
PHOTO_PRINT_DPI = 200       # resolusi maksimum foto yang disematkan di PDF
PHOTO_JPEG_QUALITY = 85

MONTHS_ID = (
    "Januari", "Februari", "Maret", "April", "Mei", "Juni",
    "Juli", "Agustus", "September", "Oktober", "November", "Desember",
)
WEEKDAYS_ID = ("Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu")

REPORT_LABEL = "LAPORAN REKAPITULASI JURNAL KEGIATAN"
TAGLINE = "Every Activity Leaves a Trace."


# =============================================================================
# BRAND MARK
# =============================================================================

class _ActraceLogo(Flowable):
    """Wordmark dan simbol ACTRACE yang digambar langsung ke PDF."""

    def __init__(self, width=66 * mm, height=18 * mm):
        super().__init__()
        self.width = width
        self.height = height
        self.hAlign = "LEFT"

    def draw(self):
        c = self.canv
        c.saveState()

        # Simbol: kotak navy dengan jejak aktivitas (pulse) putih.
        c.setFillColor(NAVY)
        c.roundRect(0, 2 * mm, 14 * mm, 14 * mm, 2.2 * mm, stroke=0, fill=1)

        c.setStrokeColor(WHITE)
        c.setLineWidth(1.4)
        c.setLineCap(1)
        c.setLineJoin(1)
        path = c.beginPath()
        path.moveTo(2.6 * mm, 9 * mm)
        path.lineTo(5.2 * mm, 9 * mm)
        path.lineTo(6.6 * mm, 12.8 * mm)
        path.lineTo(8.6 * mm, 5.2 * mm)
        path.lineTo(10.0 * mm, 9 * mm)
        path.lineTo(11.4 * mm, 9 * mm)
        c.drawPath(path, stroke=1, fill=0)

        c.setFillColor(TEAL)
        c.circle(11.4 * mm, 9 * mm, 0.9 * mm, stroke=0, fill=1)

        # Wordmark.
        c.setFillColor(NAVY)
        c.setFont("Helvetica-Bold", 17)
        c.drawString(18 * mm, 8.6 * mm, "ACTRACE")

        c.setFillColor(MUTED)
        c.setFont("Helvetica", 6.5)
        c.drawString(18 * mm, 4.2 * mm, "DIGITAL ACTIVITY JOURNAL")

        c.restoreState()


class _EntrySeparator(Flowable):
    """
    Garis tipis antar-entri jurnal. Tidak digambar (tinggi nol) bila berada
    di puncak halaman, sehingga tidak pernah muncul sebagai garis yatim
    setelah page break.
    """

    def __init__(self, gap=6 * mm):
        super().__init__()
        self.gap = gap
        self._skip = False

    def wrap(self, availWidth, availHeight):
        frame = getattr(self, "_frame", None)
        self._skip = bool(getattr(frame, "_atTop", False))
        self.width = availWidth

        return availWidth, 0 if self._skip else self.gap

    def draw(self):
        if self._skip:
            return

        c = self.canv
        c.saveState()
        c.setStrokeColor(BORDER)
        c.setLineWidth(0.5)
        c.line(0, self.gap, self.width, self.gap)
        c.restoreState()


class _NumberedCanvas(pdfcanvas.Canvas):
    """Canvas dua-pass agar nomor halaman dapat menampilkan total halaman."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._saved_page_states)

        for state in self._saved_page_states:
            self.__dict__.update(state)
            self._draw_page_number(total)
            super().showPage()

        super().save()

    def _draw_page_number(self, total):
        # Halaman sampul tidak diberi nomor.
        if self._pageNumber <= 1:
            return

        self.saveState()
        self.setFillColor(MUTED)
        self.setFont("Helvetica", 7.5)
        self.drawRightString(
            PAGE_WIDTH - MARGIN_X,
            9 * mm,
            f"Halaman {self._pageNumber} dari {total}",
        )
        self.restoreState()


# =============================================================================
# FORMAT HELPERS
# =============================================================================

def _to_date(value):
    """Ubah date/datetime/string ISO menjadi date; None bila tidak dapat."""
    if isinstance(value, datetime):
        return value.date()

    if isinstance(value, date):
        return value

    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None

    return None


def _format_date(value):
    parsed = _to_date(value)

    if parsed is not None:
        return f"{parsed.day:02d} {MONTHS_ID[parsed.month - 1]} {parsed.year}"

    if value is None:
        return "-"

    return str(value)


def _format_date_with_weekday(value):
    parsed = _to_date(value)
    formatted = _format_date(value)

    if parsed is None:
        return formatted

    return f"{WEEKDAYS_ID[parsed.weekday()]}, {formatted}"


def _format_datetime(value):
    if value is None:
        return "Tidak tersedia"

    if isinstance(value, str):
        return value

    if hasattr(value, "strftime"):
        return value.strftime("%d-%m-%Y %H:%M:%S")

    return str(value)


def _safe_int(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _paragraph(value, preserve_lines=True):
    """Escape seluruh konten pengguna sebelum diproses sebagai markup ReportLab."""
    text = escape(str(value if value is not None else ""))

    if preserve_lines:
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = "<br/>".join(text.split("\n"))

    return text


# =============================================================================
# PHOTO HANDLING
# =============================================================================

def _resolve_photo(photo, upload_root):
    """Resolve foto hanya dari file_path database dan batasi ke upload root."""
    if not upload_root:
        return None

    try:
        root = Path(upload_root).resolve()
        relative = Path(str(photo.get("file_path") or ""))

        if relative.is_absolute():
            return None

        candidate = (root / relative).resolve()
        candidate.relative_to(root)

        if not candidate.is_file():
            return None

        # Verify image content before handing it to ReportLab.
        with PILImage.open(candidate) as source:
            source.verify()

        return candidate

    except (
        OSError, ValueError, TypeError, SyntaxError,
        UnidentifiedImageError, PILImage.DecompressionBombError,
    ):
        logger.warning(
            "Foto jurnal tidak dapat digunakan pada PDF. photo_id=%s",
            photo.get("photo_id"),
        )
        return None


def _prepare_photo(path, target_width_pt, target_height_pt):
    """
    Baca foto, terapkan orientasi EXIF, ratakan transparansi ke putih, dan
    perkecil ke resolusi cetak yang cukup. Hasilnya disimpan di memori;
    berkas asli di upload folder tidak pernah diubah.

    Mengembalikan (buffer_jpeg, lebar_px, tinggi_px) atau None.
    """
    with PILImage.open(path) as source:
        image = ImageOps.exif_transpose(source)
        image.load()

    if image.mode in ("RGBA", "LA") or (
        image.mode == "P" and "transparency" in image.info
    ):
        rgba = image.convert("RGBA")
        flattened = PILImage.new("RGB", rgba.size, (255, 255, 255))
        flattened.paste(rgba, mask=rgba.getchannel("A"))
        image = flattened
    elif image.mode != "RGB":
        image = image.convert("RGB")

    width, height = image.size

    if not width or not height:
        return None

    # Batas piksel untuk kualitas cetak ~PHOTO_PRINT_DPI pada ukuran tampil.
    max_px_w = max(1, int(target_width_pt / 72 * PHOTO_PRINT_DPI))
    max_px_h = max(1, int(target_height_pt / 72 * PHOTO_PRINT_DPI))

    if width > max_px_w or height > max_px_h:
        image.thumbnail((max_px_w, max_px_h), PILImage.LANCZOS)
        width, height = image.size

    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=PHOTO_JPEG_QUALITY, optimize=True)
    buffer.seek(0)

    return buffer, width, height


def _make_photo_flowable(path, max_width=78 * mm, max_height=PHOTO_MAX_HEIGHT):
    """
    Skala foto ke dalam kotak max_width x max_height tanpa crop/distorsi.

    Rasio aspek dihitung dari foto setelah orientasi EXIF diterapkan, dan
    foto tidak pernah diperbesar melebihi ukuran aslinya (1 px = 1 pt).
    """
    try:
        prepared = _prepare_photo(path, max_width, max_height)

        if prepared is None:
            return None

        buffer, px_width, px_height = prepared

        # Ukuran tampil dihitung dari piksel setelah koreksi orientasi.
        scale = min(max_width / px_width, max_height / px_height, 1)

        flowable = Image(
            buffer,
            width=px_width * scale,
            height=px_height * scale,
        )
        flowable.hAlign = "CENTER"

        return flowable

    except (
        OSError, ValueError, SyntaxError, TypeError,
        UnidentifiedImageError, PILImage.DecompressionBombError,
    ):
        return None


# =============================================================================
# STYLES
# =============================================================================

def _build_styles():
    styles = getSampleStyleSheet()

    def add(name, parent="Normal", **kwargs):
        styles.add(ParagraphStyle(name=name, parent=styles[parent], **kwargs))

    add("ActraceEyebrow",
        fontName="Helvetica-Bold", fontSize=8.5, leading=12,
        textColor=TEAL, spaceAfter=6)

    add("ActraceCoverTitle", "Title",
        fontName="Helvetica-Bold", fontSize=30, leading=36,
        alignment=TA_LEFT, textColor=NAVY, spaceAfter=0)

    add("ActraceSubtitle",
        fontSize=9.5, leading=15, textColor=MUTED)

    add("ActraceSection", "Heading2",
        fontName="Helvetica-Bold", fontSize=14, leading=18,
        textColor=NAVY, spaceBefore=0, spaceAfter=3, keepWithNext=1)

    add("ActraceBlockTitle",
        fontName="Helvetica-Bold", fontSize=8, leading=11,
        textColor=NAVY, spaceAfter=5)

    add("ActraceDate",
        fontName="Helvetica-Bold", fontSize=9.5, leading=13,
        textColor=TEAL, spaceAfter=1)

    add("ActraceJournalTitle", "Heading3",
        fontName="Helvetica-Bold", fontSize=12.5, leading=16,
        textColor=NAVY, spaceBefore=0, spaceAfter=0, splitLongWords=1)

    add("ActraceBadge",
        fontName="Helvetica-Bold", fontSize=13, leading=16,
        textColor=WHITE, alignment=TA_CENTER)

    add("ActraceBody", "BodyText",
        fontName="Helvetica", fontSize=9.5, leading=15,
        textColor=TEXT, spaceAfter=0, splitLongWords=1)

    add("ActraceEmpty", "BodyText",
        fontName="Helvetica-Oblique", fontSize=9, leading=14,
        textColor=MUTED, splitLongWords=1)

    add("ActraceMeta",
        fontName="Helvetica", fontSize=7.5, leading=11,
        textColor=MUTED, splitLongWords=1)

    add("ActraceLabel",
        fontName="Helvetica-Bold", fontSize=7.5, leading=10,
        textColor=MUTED, keepWithNext=1)

    add("ActraceStat",
        fontName="Helvetica-Bold", fontSize=24, leading=28,
        textColor=NAVY)

    add("ActraceSmall",
        fontSize=9, leading=13, textColor=TEXT, splitLongWords=1)

    add("ActracePeriod",
        fontName="Helvetica-Bold", fontSize=10, leading=14,
        textColor=NAVY)

    add("ActraceCenter",
        fontSize=9.5, leading=15, textColor=MUTED, alignment=TA_CENTER)

    return styles


# =============================================================================
# LAYOUT HELPERS
# =============================================================================

def _accent_rule(width=28 * mm, space_before=0, space_after=4 * mm):
    return HRFlowable(
        width=width, thickness=2.2, color=TEAL, hAlign="LEFT",
        spaceBefore=space_before, spaceAfter=space_after,
    )


def _section_heading(text, styles):
    return [
        Paragraph(_paragraph(text), styles["ActraceSection"]),
        _accent_rule(),
    ]


def _key_value_table(rows, styles, label_width=46 * mm):
    """Tabel identitas dua kolom dengan garis pemisah tipis."""
    data = [
        [
            Paragraph(_paragraph(label), styles["ActraceLabel"]),
            Paragraph(_paragraph(value), styles["ActraceSmall"]),
        ]
        for label, value in rows
    ]

    table = Table(data, colWidths=[label_width, USABLE_WIDTH - label_width])
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEABOVE", (0, 0), (-1, 0), 1.2, NAVY),
        ("LINEBELOW", (0, 0), (-1, -1), 0.5, BORDER),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
    ]))

    return table


def _stat_cards(items, styles):
    """Kartu statistik berjajar dengan jarak antar-kartu."""
    gap = 4 * mm
    count = len(items)
    card_width = (USABLE_WIDTH - gap * (count - 1)) / count

    cells = []
    widths = []
    style = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]

    for index, (label, value) in enumerate(items):
        col = index * 2

        card = Table(
            [
                [Paragraph(_paragraph(value), styles["ActraceStat"])],
                [Paragraph(_paragraph(label), styles["ActraceLabel"])],
            ],
            colWidths=[card_width],
        )
        card.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), LIGHT),
            ("LINEABOVE", (0, 0), (-1, 0), 2.2, TEAL),
            ("LEFTPADDING", (0, 0), (-1, -1), 11),
            ("RIGHTPADDING", (0, 0), (-1, -1), 11),
            ("TOPPADDING", (0, 0), (0, 0), 12),
            ("BOTTOMPADDING", (0, 0), (0, 0), 2),
            ("TOPPADDING", (0, 1), (0, 1), 0),
            ("BOTTOMPADDING", (0, 1), (0, 1), 12),
        ]))

        cells.append(card)
        widths.append(card_width)

        if index < count - 1:
            cells.append("")
            widths.append(gap)

    table = Table([cells], colWidths=widths)
    table.setStyle(TableStyle(style))

    return table


def _period_table(start_date, end_date, first_date, last_date, styles):
    columns = [
        ("PERIODE LAPORAN",
         f"{_format_date(start_date)} – {_format_date(end_date)}"),
        ("AKTIVITAS PERTAMA", first_date),
        ("AKTIVITAS TERAKHIR", last_date),
    ]

    widths = [USABLE_WIDTH * 0.46, USABLE_WIDTH * 0.27, USABLE_WIDTH * 0.27]

    table = Table(
        [
            [Paragraph(label, styles["ActraceLabel"]) for label, _ in columns],
            [
                Paragraph(_paragraph(value), styles["ActraceSmall"])
                for _, value in columns
            ],
        ],
        colWidths=widths,
    )
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, -1), (-1, -1), 0.5, BORDER),
        ("LINEABOVE", (0, 0), (-1, 0), 0.5, BORDER),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, 0), 8),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 2),
        ("TOPPADDING", (0, 1), (-1, 1), 0),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 8),
    ]))

    return table


def _photo_caption(photo, number):
    file_name = photo.get("file_name") or "Nama file tidak tersedia"
    uploaded = _format_datetime(photo.get("uploaded_at"))

    return (
        f"<b>Dokumentasi {number}</b>"
        f" &nbsp;·&nbsp; {_paragraph(file_name, preserve_lines=False)}<br/>"
        f"Diunggah: {_paragraph(uploaded, preserve_lines=False)}"
    )


def _photo_cell(photo, number, cell_width, image, image_height, styles):
    """
    Satu sel foto: area gambar + keterangan.

    `image` adalah Flowable gambar (atau None bila foto tidak dapat dipakai)
    dan `image_height` tinggi area gambar yang dibagi seluruh sel pada baris
    yang sama, sehingga tepi kartu dalam satu baris selalu sejajar.
    """
    caption = Paragraph(_photo_caption(photo, number), styles["ActraceMeta"])

    if image is None:
        image = Paragraph(
            f"<font color='#{ERROR.hexval()[2:]}'>"
            "File foto tidak tersedia<br/>atau tidak valid.</font>",
            styles["ActraceCenter"],
        )

    cell = Table(
        [[image], [caption]],
        colWidths=[cell_width],
        rowHeights=[image_height + 2 * PHOTO_CELL_PAD, None],
    )
    cell.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.5, BORDER),
        ("BACKGROUND", (0, 0), (0, 0), LIGHT),
        ("ALIGN", (0, 0), (0, 0), "CENTER"),
        ("VALIGN", (0, 0), (0, 0), "MIDDLE"),
        ("LINEBELOW", (0, 0), (0, 0), 0.5, BORDER),
        ("LEFTPADDING", (0, 0), (-1, -1), PHOTO_CELL_PAD),
        ("RIGHTPADDING", (0, 0), (-1, -1), PHOTO_CELL_PAD),
        ("TOPPADDING", (0, 0), (0, 0), PHOTO_CELL_PAD),
        ("BOTTOMPADDING", (0, 0), (0, 0), PHOTO_CELL_PAD),
        ("TOPPADDING", (0, 1), (0, 1), 6),
        ("BOTTOMPADDING", (0, 1), (0, 1), 6),
    ]))

    return cell


def _photo_gallery(photos, photo_root, styles):
    """
    Grid dua kolom. Setiap baris adalah tabel tersendiri sehingga halaman
    dapat berpindah di antara baris foto tanpa memotong gambar.
    """
    label = Paragraph("DOKUMENTASI KEGIATAN", styles["ActraceLabel"])

    cell_width = (USABLE_WIDTH - PHOTO_GUTTER) / 2
    inner_width = cell_width - 2 * PHOTO_CELL_PAD
    placeholder_height = 26 * mm

    items = []

    for number, photo in enumerate(photos, start=1):
        path = _resolve_photo(photo, photo_root)
        image = _make_photo_flowable(path, max_width=inner_width) if path else None
        items.append((number, photo, image))

    rows = []

    for start in range(0, len(items), 2):
        pair = items[start:start + 2]

        image_height = max(
            (image.drawHeight for _, _, image in pair if image is not None),
            default=placeholder_height,
        )

        cells = [
            _photo_cell(photo, number, cell_width, image, image_height, styles)
            for number, photo, image in pair
        ]

        if len(items) == 1:
            # Foto tunggal: tampil di tengah.
            row = Table([[cells[0]]], colWidths=[cell_width], hAlign="CENTER")
        else:
            right_cell = cells[1] if len(cells) > 1 else ""
            row = Table(
                [[cells[0], "", right_cell]],
                colWidths=[cell_width, PHOTO_GUTTER, cell_width],
                hAlign="LEFT",
            )

        row.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]))

        rows.append(row)

    flowables = [label, Spacer(1, 1.5 * mm)]

    for position, row in enumerate(rows):
        if position:
            flowables.append(Spacer(1, PHOTO_GUTTER))
        flowables.append(row)

    # Label dan baris foto pertama selalu berada di halaman yang sama.
    return [KeepTogether(flowables[:3])] + flowables[3:]


def _journal_entry(index, journal, photo_root, styles):
    """Susun seluruh flowable untuk satu entri jurnal."""
    photos = journal.get("photos") or []
    photo_count = (
        len(photos) if "photos" in journal
        else _safe_int(journal.get("photo_count"))
    )

    title = journal.get("title") or "Tanpa judul"
    description = journal.get("description")

    header = Table(
        [[
            Paragraph(f"{index:02d}", styles["ActraceBadge"]),
            [
                Paragraph(
                    _paragraph(
                        _format_date_with_weekday(journal.get("activity_date"))
                    ),
                    styles["ActraceDate"],
                ),
                Paragraph(_paragraph(title), styles["ActraceJournalTitle"]),
            ],
        ]],
        colWidths=[BADGE_WIDTH, USABLE_WIDTH - BADGE_WIDTH],
    )
    header.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, 0), NAVY),
        ("BACKGROUND", (1, 0), (1, 0), LIGHT),
        ("VALIGN", (0, 0), (0, 0), "MIDDLE"),
        ("VALIGN", (1, 0), (1, 0), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (0, 0), 0),
        ("RIGHTPADDING", (0, 0), (0, 0), 0),
        ("LEFTPADDING", (1, 0), (1, 0), 12),
        ("RIGHTPADDING", (1, 0), (1, 0), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
    ]))

    meta_line = (
        f"ID Jurnal: {_paragraph(journal.get('journal_id', '-'), False)}"
        f" &nbsp;|&nbsp; Dokumentasi foto: {photo_count}"
    )

    if description is not None and str(description).strip():
        body = Paragraph(_paragraph(description), styles["ActraceBody"])
    else:
        body = Paragraph("Tidak ada deskripsi kegiatan.", styles["ActraceEmpty"])

    # Pastikan judul entri tidak terpisah dari awal deskripsinya, dan entri
    # berfoto tidak terpisah dari baris foto pertamanya bila masih muat.
    min_space = 100 * mm if photos else 48 * mm

    entry = [CondPageBreak(min_space)]

    # Garis tipis memisahkan entri. Ditempatkan setelah CondPageBreak dan
    # dilewati otomatis di puncak halaman.
    if index > 1:
        entry.append(_EntrySeparator())

    entry.extend([
        header,
        Spacer(1, 2 * mm),
        Paragraph(meta_line, styles["ActraceMeta"]),
        Spacer(1, 3.5 * mm),
        body,
        Spacer(1, 4 * mm),
    ])

    if photos:
        entry.extend(_photo_gallery(photos, photo_root, styles))
    else:
        entry.append(Paragraph(
            "Tidak ada dokumentasi foto untuk jurnal ini."
            if not photo_count
            else "Berkas foto tidak disertakan pada data laporan ini.",
            styles["ActraceEmpty"],
        ))

    entry.extend([
        Spacer(1, 3 * mm),
        Paragraph(
            f"Dibuat: {_paragraph(_format_datetime(journal.get('created_at')))}"
            f" &nbsp;&nbsp;|&nbsp;&nbsp; "
            f"Diperbarui: "
            f"{_paragraph(_format_datetime(journal.get('updated_at')))}",
            styles["ActraceMeta"],
        ),
        Spacer(1, 6 * mm),
    ])

    return entry


# =============================================================================
# PAGE CHROME (header / footer)
# =============================================================================

def _draw_footer(canvas):
    canvas.setStrokeColor(BORDER)
    canvas.setLineWidth(0.5)
    canvas.line(MARGIN_X, 14 * mm, PAGE_WIDTH - MARGIN_X, 14 * mm)

    canvas.setFillColor(MUTED)
    canvas.setFont("Helvetica-Oblique", 7.5)
    canvas.drawString(MARGIN_X, 9 * mm, TAGLINE)


def _draw_cover_page(canvas, document):
    canvas.saveState()

    # Pita navy tipis dengan aksen teal di tepi atas.
    canvas.setFillColor(NAVY)
    canvas.rect(0, PAGE_HEIGHT - 7 * mm, PAGE_WIDTH, 7 * mm, stroke=0, fill=1)
    canvas.setFillColor(TEAL)
    canvas.rect(0, PAGE_HEIGHT - 7 * mm, 38 * mm, 7 * mm, stroke=0, fill=1)

    _draw_footer(canvas)
    canvas.restoreState()


def _draw_content_page(canvas, document):
    canvas.saveState()

    canvas.setStrokeColor(BORDER)
    canvas.setLineWidth(0.5)
    canvas.line(
        MARGIN_X, PAGE_HEIGHT - 15 * mm,
        PAGE_WIDTH - MARGIN_X, PAGE_HEIGHT - 15 * mm,
    )

    canvas.setFillColor(NAVY)
    canvas.setFont("Helvetica-Bold", 8)
    canvas.drawString(MARGIN_X, PAGE_HEIGHT - 11 * mm, "ACTRACE")

    canvas.setFillColor(MUTED)
    canvas.setFont("Helvetica", 7.5)
    canvas.drawRightString(
        PAGE_WIDTH - MARGIN_X, PAGE_HEIGHT - 11 * mm, REPORT_LABEL,
    )

    _draw_footer(canvas)
    canvas.restoreState()


# =============================================================================
# REPORT SECTIONS
# =============================================================================

def _cover_story(student, start_date, end_date, generated_at, styles):
    identity = [
        ("NAMA LENGKAP", student.get("full_name") or "Tidak tersedia"),
        ("NIS / NISN", student.get("student_code") or "Tidak tersedia"),
        (
            "PERIODE LAPORAN",
            f"{_format_date(start_date)} – {_format_date(end_date)}",
        ),
        ("TANGGAL PEMBUATAN", _format_date(generated_at.date())),
    ]

    return [
        _ActraceLogo(),
        Spacer(1, 38 * mm),
        Paragraph("LAPORAN KEGIATAN SISWA", styles["ActraceEyebrow"]),
        Paragraph(
            "Laporan Rekapitulasi<br/>Jurnal Kegiatan",
            styles["ActraceCoverTitle"],
        ),
        _accent_rule(width=34 * mm, space_before=7 * mm, space_after=6 * mm),
        Paragraph(
            "Dokumen rekapitulasi aktivitas siswa berdasarkan periode "
            "yang dipilih.",
            styles["ActraceSubtitle"],
        ),
        Spacer(1, 26 * mm),
        Paragraph("IDENTITAS SISWA", styles["ActraceBlockTitle"]),
        _key_value_table(identity, styles),
        PageBreak(),
    ]


def _summary_story(journals, start_date, end_date, styles):
    unique_days = {
        str(j.get("activity_date"))[:10]
        for j in journals
        if j.get("activity_date") is not None
    }

    total_photos = sum(len(j.get("photos") or []) for j in journals)

    if not total_photos:
        total_photos = sum(_safe_int(j.get("photo_count")) for j in journals)

    parsed_dates = [
        parsed for parsed in (_to_date(j.get("activity_date")) for j in journals)
        if parsed is not None
    ]

    first_date = _format_date(min(parsed_dates)) if parsed_dates else "-"
    last_date = _format_date(max(parsed_dates)) if parsed_dates else "-"

    story = _section_heading("Ringkasan Kegiatan", styles)
    story.extend([
        Paragraph(
            "Statistik berikut dihitung dari jurnal yang ditemukan pada "
            "periode laporan.",
            styles["ActraceSubtitle"],
        ),
        Spacer(1, 6 * mm),
        _stat_cards(
            [
                ("TOTAL JURNAL", str(len(journals))),
                ("HARI KEGIATAN", str(len(unique_days))),
                ("DOKUMENTASI FOTO", str(total_photos)),
            ],
            styles,
        ),
        Spacer(1, 6 * mm),
        _period_table(start_date, end_date, first_date, last_date, styles),
        Spacer(1, 12 * mm),
    ])

    return story, len(unique_days), total_photos


def _closing_story(journal_count, day_count, total_photos,
                   start_date, end_date, generated_at, styles):
    block = _section_heading("Penutup Laporan", styles)
    block.extend([
        Paragraph(
            f"Laporan ini memuat {journal_count} jurnal kegiatan, "
            f"{day_count} hari kegiatan tercatat, dan "
            f"{total_photos} dokumentasi foto pada periode "
            f"{_format_date(start_date)} sampai {_format_date(end_date)}.",
            styles["ActraceBody"],
        ),
        Spacer(1, 5 * mm),
        Paragraph(
            f"Dokumen dibuat secara otomatis oleh ACTRACE "
            f"pada {_format_date(generated_at.date())}.",
            styles["ActraceMeta"],
        ),
    ])

    return [Spacer(1, 4 * mm), KeepTogether(block)]


# =============================================================================
# PUBLIC API
# =============================================================================

def build_journal_report_pdf(
    student,
    journals,
    start_date,
    end_date,
    photo_root=None,
):
    """
    Membangun PDF lengkap dari data yang telah difilter dan diotorisasi route.
    Informasi identitas yang tidak tersedia di database tidak direka.
    """
    output = BytesIO()
    generated_at = datetime.now()
    journals = list(journals or [])
    student = student or {}

    doc = SimpleDocTemplate(
        output,
        pagesize=A4,
        rightMargin=MARGIN_X,
        leftMargin=MARGIN_X,
        topMargin=MARGIN_TOP,
        bottomMargin=MARGIN_BOTTOM,
        title="Laporan Rekapitulasi Jurnal Kegiatan - ACTRACE",
        author="ACTRACE",
        subject="Rekapitulasi aktivitas siswa",
    )

    styles = _build_styles()

    story = _cover_story(student, start_date, end_date, generated_at, styles)

    summary, day_count, total_photos = _summary_story(
        journals, start_date, end_date, styles,
    )
    story.extend(summary)

    story.extend(_section_heading("Detail Seluruh Jurnal", styles))

    if not journals:
        story.extend([
            Spacer(1, 8 * mm),
            Paragraph(
                "Tidak terdapat jurnal kegiatan pada rentang tanggal "
                "yang dipilih.",
                styles["ActraceCenter"],
            ),
        ])
    else:
        story.append(Spacer(1, 2 * mm))

        for index, journal in enumerate(journals, start=1):
            story.extend(_journal_entry(index, journal, photo_root, styles))

    story.extend(_closing_story(
        len(journals), day_count, total_photos,
        start_date, end_date, generated_at, styles,
    ))

    doc.build(
        story,
        onFirstPage=_draw_cover_page,
        onLaterPages=_draw_content_page,
        canvasmaker=_NumberedCanvas,
    )

    output.seek(0)

    return output