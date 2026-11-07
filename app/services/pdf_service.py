"""Pembuatan PDF rekap jurnal lengkap ACTRACE."""

import logging
from datetime import date, datetime
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

from PIL import Image as PILImage, UnidentifiedImageError

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, Image, KeepTogether, HRFlowable, Flowable,
)

logger = logging.getLogger(__name__)


class _ActraceLogo(Flowable):
    """Wordmark dan simbol geometris ACTRACE yang digambar langsung ke PDF."""

    def __init__(self, width=66 * mm, height=18 * mm):
        super().__init__()
        self.width = width
        self.height = height

    def draw(self):
        c = self.canv

        # Record-like geometric mark with a continuous activity trace.
        c.saveState()
        c.setStrokeColor(CYAN)
        c.setLineWidth(1.8)
        c.roundRect(1, 2, 14 * mm, 14 * mm, 2 * mm, stroke=1, fill=0)
        c.line(4 * mm, 11 * mm, 11 * mm, 11 * mm)
        c.line(4 * mm, 8 * mm, 8 * mm, 8 * mm)

        c.setStrokeColor(BLUE)
        path = c.beginPath()
        path.moveTo(3.5 * mm, 5 * mm)
        path.lineTo(6 * mm, 7 * mm)
        path.lineTo(8 * mm, 5.5 * mm)
        path.lineTo(12 * mm, 9 * mm)
        c.drawPath(path, stroke=1, fill=0)

        c.setFillColor(NAVY)
        c.setFont("Helvetica-Bold", 16)
        c.drawString(19 * mm, 6 * mm, "ACTRACE")

        c.setFillColor(MUTED)
        c.setFont("Helvetica", 6.5)
        c.drawString(19 * mm, 2 * mm, "DIGITAL ACTIVITY JOURNAL")
        c.restoreState()


NAVY = colors.HexColor("#10243A")
BLUE = colors.HexColor("#2563EB")
CYAN = colors.HexColor("#21A6B5")
TEXT = colors.HexColor("#334155")
MUTED = colors.HexColor("#64748B")
BORDER = colors.HexColor("#DCE5EE")
PALE = colors.HexColor("#F3F7FA")
WHITE = colors.white


def _format_date(value):
    if isinstance(value, str):
        try:
            value = date.fromisoformat(value[:10])
        except ValueError:
            return value

    if hasattr(value, "strftime"):
        months = (
            "Januari", "Februari", "Maret", "April", "Mei", "Juni",
            "Juli", "Agustus", "September", "Oktober", "November", "Desember",
        )
        return f"{value.day:02d} {months[value.month - 1]} {value.year}"

    return str(value) if value is not None else "-"


def _format_datetime(value):
    if value is None:
        return "Tidak tersedia"

    if isinstance(value, str):
        return value

    if hasattr(value, "strftime"):
        return value.strftime("%d-%m-%Y %H:%M:%S")

    return str(value)


def _paragraph(value, preserve_lines=True):
    """Escape seluruh konten pengguna sebelum diproses sebagai markup ReportLab."""
    text = escape(str(value if value is not None else ""))

    if preserve_lines:
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = "<br/>".join(text.split("\n"))

    return text


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

    except (OSError, ValueError, TypeError, UnidentifiedImageError):
        logger.warning(
            "Foto jurnal tidak dapat digunakan pada PDF. photo_id=%s",
            photo.get("photo_id"),
        )
        return None


def _make_photo_flowable(path, max_width=78 * mm, max_height=55 * mm):
    try:
        with PILImage.open(path) as source:
            width, height = source.size

        if not width or not height:
            return None

        scale = min(max_width / width, max_height / height, 1)

        flowable = Image(
            str(path),
            width=width * scale,
            height=height * scale,
        )
        flowable.hAlign = "CENTER"

        return flowable

    except (OSError, ValueError, UnidentifiedImageError):
        return None


def _build_styles():
    styles = getSampleStyleSheet()

    styles.add(ParagraphStyle(
        name="ActraceEyebrow",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8,
        leading=11,
        textColor=MUTED,
        tracking=1.0,
        spaceAfter=5,
    ))

    styles.add(ParagraphStyle(
        name="ActraceCoverTitle",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=21,
        leading=27,
        alignment=TA_LEFT,
        textColor=NAVY,
        spaceAfter=8,
    ))

    styles.add(ParagraphStyle(
        name="ActraceSubtitle",
        parent=styles["Normal"],
        fontSize=9,
        leading=14,
        textColor=MUTED,
    ))

    styles.add(ParagraphStyle(
        name="ActraceSection",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=14,
        leading=18,
        textColor=NAVY,
        spaceBefore=4,
        spaceAfter=9,
    ))

    styles.add(ParagraphStyle(
        name="ActraceJournalTitle",
        parent=styles["Heading3"],
        fontName="Helvetica-Bold",
        fontSize=11,
        leading=15,
        textColor=NAVY,
        spaceAfter=3,
    ))

    styles.add(ParagraphStyle(
        name="ActraceBody",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=9,
        leading=14,
        textColor=TEXT,
        spaceAfter=4,
        splitLongWords=1,
    ))

    styles.add(ParagraphStyle(
        name="ActraceMeta",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=7.5,
        leading=11,
        textColor=MUTED,
        splitLongWords=1,
    ))

    styles.add(ParagraphStyle(
        name="ActraceLabel",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=7.5,
        leading=10,
        textColor=MUTED,
    ))

    styles.add(ParagraphStyle(
        name="ActraceStat",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=17,
        leading=20,
        textColor=NAVY,
    ))

    styles.add(ParagraphStyle(
        name="ActraceSmall",
        parent=styles["Normal"],
        fontSize=8,
        leading=11,
        textColor=TEXT,
    ))

    styles.add(ParagraphStyle(
        name="ActraceCenter",
        parent=styles["Normal"],
        fontSize=9,
        leading=14,
        textColor=MUTED,
        alignment=TA_CENTER,
    ))

    return styles


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
    page_width, page_height = A4

    left = right = 19 * mm
    usable_width = page_width - left - right
    generated_at = datetime.now()
    journals = list(journals or [])

    doc = SimpleDocTemplate(
        output,
        pagesize=A4,
        rightMargin=right,
        leftMargin=left,
        topMargin=23 * mm,
        bottomMargin=20 * mm,
        title="Laporan Rekapitulasi Jurnal Kegiatan - ACTRACE",
        author="ACTRACE",
        subject="Rekapitulasi aktivitas siswa",
    )

    styles = _build_styles()
    story = []

    # =========================================
    # COVER
    # =========================================

    story.extend([
        _ActraceLogo(),
        Spacer(1, 8 * mm),
        Paragraph(
            "LAPORAN KEGIATAN SISWA",
            styles["ActraceEyebrow"],
        ),
        HRFlowable(
            width="100%",
            thickness=2,
            color=CYAN,
            spaceBefore=2,
            spaceAfter=12,
        ),
        Paragraph(
            "LAPORAN REKAPITULASI<br/>JURNAL KEGIATAN",
            styles["ActraceCoverTitle"],
        ),
        Paragraph(
            "Dokumen rekapitulasi aktivitas siswa berdasarkan periode yang dipilih.",
            styles["ActraceSubtitle"],
        ),
        Spacer(1, 13 * mm),
    ])

    identity = [
        ("Nama lengkap", student.get("full_name") or "Tidak tersedia"),
        ("NIS / NISN", student.get("student_code") or "Tidak tersedia"),
        ("Kelas", "Tidak tersedia pada data akun"),
        ("Jurusan", "Tidak tersedia pada data akun"),
        ("Sekolah", "Tidak tersedia pada data akun"),
        ("Instansi / tempat PKL", "Tidak tersedia pada data akun"),
        (
            "Periode laporan",
            f"{_format_date(start_date)} – {_format_date(end_date)}",
        ),
        ("Tanggal pembuatan", _format_date(generated_at.date())),
    ]

    identity_rows = []

    for label, value in identity:
        identity_rows.append([
            Paragraph(_paragraph(label), styles["ActraceLabel"]),
            Paragraph(_paragraph(value), styles["ActraceSmall"]),
        ])

    identity_table = Table(
        identity_rows,
        colWidths=[48 * mm, usable_width - 48 * mm],
    )

    identity_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PALE),
        ("BOX", (0, 0), (-1, -1), 0.7, BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.35, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
    ]))

    story.extend([
        identity_table,
        Spacer(1, 15 * mm),
    ])

    story.append(Paragraph(
        "Every Activity Leaves a Trace.",
        ParagraphStyle(
            "CoverTagline",
            parent=styles["ActraceSubtitle"],
            fontName="Helvetica-Oblique",
            textColor=CYAN,
            fontSize=10,
        ),
    ))

    story.append(PageBreak())

    # =========================================
    # SUMMARY
    # =========================================

    unique_days = {
        str(j.get("activity_date"))[:10]
        for j in journals
        if j.get("activity_date") is not None
    }

    total_photos = sum(
        len(j.get("photos") or [])
        for j in journals
    )

    if not total_photos:
        total_photos = sum(
            int(j.get("photo_count") or 0)
            for j in journals
        )

    story.extend([
        Paragraph(
            "RINGKASAN KEGIATAN",
            styles["ActraceSection"],
        ),
        Paragraph(
            "Statistik berikut dihitung dari jurnal yang ditemukan pada periode laporan.",
            styles["ActraceSubtitle"],
        ),
        Spacer(1, 5 * mm),
    ])

    stat_items = [
        ("TOTAL JURNAL", str(len(journals))),
        ("HARI KEGIATAN", str(len(unique_days))),
        ("DOKUMENTASI FOTO", str(total_photos)),
    ]

    stat_cells = []

    for label, value in stat_items:
        stat_cells.append([
            Paragraph(_paragraph(value), styles["ActraceStat"]),
            Paragraph(_paragraph(label), styles["ActraceLabel"]),
        ])

    stat_table = Table(
        [stat_cells],
        colWidths=[usable_width / 3] * 3,
    )

    stat_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PALE),
        ("BOX", (0, 0), (-1, -1), 0.7, BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 9),
        ("RIGHTPADDING", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 12),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
    ]))

    story.extend([
        stat_table,
        Spacer(1, 7 * mm),
    ])

    first_date = (
        _format_date(journals[0].get("activity_date"))
        if journals else "-"
    )

    last_date = (
        _format_date(journals[-1].get("activity_date"))
        if journals else "-"
    )

    summary_rows = [
        [
            Paragraph("Aktivitas pertama", styles["ActraceLabel"]),
            Paragraph("Aktivitas terakhir", styles["ActraceLabel"]),
        ],
        [
            Paragraph(_paragraph(first_date), styles["ActraceSmall"]),
            Paragraph(_paragraph(last_date), styles["ActraceSmall"]),
        ],
    ]

    date_table = Table(
        summary_rows,
        colWidths=[usable_width / 2] * 2,
    )

    date_table.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 9),
        ("RIGHTPADDING", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))

    story.append(date_table)
    story.append(Spacer(1, 10 * mm))

    story.append(Paragraph(
        "DETAIL SELURUH JURNAL",
        styles["ActraceSection"],
    ))

    if not journals:
        story.append(Spacer(1, 10 * mm))

        story.append(Paragraph(
            "Tidak terdapat jurnal kegiatan pada rentang tanggal yang dipilih.",
            styles["ActraceCenter"],
        ))

    else:
        for index, journal in enumerate(journals, start=1):
            journal_id = journal.get("journal_id", "-")
            photos = journal.get("photos") or []

            photo_count = (
                len(photos)
                if "photos" in journal
                else int(journal.get("photo_count") or 0)
            )

            heading = Paragraph(
                f"{index:02d}. "
                f"{_paragraph(journal.get('title') or 'Tanpa judul')}",
                styles["ActraceJournalTitle"],
            )

            metadata = [
                [
                    Paragraph("ID JURNAL", styles["ActraceLabel"]),
                    Paragraph("TANGGAL AKTIVITAS", styles["ActraceLabel"]),
                    Paragraph("JUMLAH FOTO", styles["ActraceLabel"]),
                ],
                [
                    Paragraph(_paragraph(journal_id), styles["ActraceSmall"]),
                    Paragraph(
                        _paragraph(_format_date(journal.get("activity_date"))),
                        styles["ActraceSmall"],
                    ),
                    Paragraph(str(photo_count), styles["ActraceSmall"]),
                ],
            ]

            meta_table = Table(
                metadata,
                colWidths=[
                    usable_width * .22,
                    usable_width * .52,
                    usable_width * .26,
                ],
            )

            meta_table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), PALE),
                ("BOX", (0, 0), (-1, -1), 0.5, BORDER),
                ("INNERGRID", (0, 0), (-1, -1), 0.35, BORDER),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]))

            story.extend([
                Spacer(1, 4 * mm),
                heading,
                meta_table,
                Spacer(1, 3 * mm),
                Paragraph(
                    "DESKRIPSI KEGIATAN",
                    styles["ActraceLabel"],
                ),
                Spacer(1, 1.5 * mm),
                Paragraph(
                    _paragraph(journal.get("description", "")),
                    styles["ActraceBody"],
                ),
                Spacer(1, 2 * mm),
            ])

            # =========================================
            # JOURNAL PHOTO DOCUMENTATION
            # =========================================

            if photos:
                story.append(Paragraph(
                    "DOKUMENTASI KEGIATAN",
                    styles["ActraceLabel"],
                ))

                gallery_cells = []

                for photo_index, photo in enumerate(photos, start=1):
                    path = _resolve_photo(photo, photo_root)

                    image_flowable = (
                        _make_photo_flowable(path)
                        if path else None
                    )

                    if image_flowable is None:
                        cell = Paragraph(
                            _paragraph(
                                f"Dokumentasi {photo_index} | "
                                f"{photo.get('file_name') or 'Nama file tidak tersedia'} | "
                                f"ID foto: {photo.get('photo_id', '-')} | "
                                f"Diunggah: {_format_datetime(photo.get('uploaded_at'))}"
                            )
                            + "<br/><font color='#9F3434'>"
                            "File foto tidak tersedia atau tidak valid."
                            "</font>",
                            styles["ActraceSmall"],
                        )

                    else:
                        cell = Table(
                            [
                                [image_flowable],
                                [
                                    Paragraph(
                                        _paragraph(
                                            f"Dokumentasi {photo_index} | "
                                            f"{photo.get('file_name') or 'Nama file tidak tersedia'} | "
                                            f"ID foto: {photo.get('photo_id', '-')} | "
                                            f"Diunggah: {_format_datetime(photo.get('uploaded_at'))}"
                                        ),
                                        styles["ActraceMeta"],
                                    )
                                ],
                            ],
                            colWidths=[usable_width / 2 - 10],
                        )

                        cell.setStyle(TableStyle([
                            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                            ("LEFTPADDING", (0, 0), (-1, -1), 1),
                            ("RIGHTPADDING", (0, 0), (-1, -1), 1),
                            ("TOPPADDING", (0, 0), (-1, -1), 1),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
                        ]))

                    gallery_cells.append(cell)

                rows = []

                for i in range(0, len(gallery_cells), 2):
                    left_cell = gallery_cells[i]

                    right_cell = (
                        gallery_cells[i + 1]
                        if i + 1 < len(gallery_cells)
                        else ""
                    )

                    rows.append([left_cell, right_cell])

                gallery = Table(
                    rows,
                    colWidths=[usable_width / 2] * 2,
                    hAlign="LEFT",
                )

                gallery.setStyle(TableStyle([
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                    ("BOX", (0, 0), (-1, -1), 0.4, BORDER),
                    ("INNERGRID", (0, 0), (-1, -1), 0.3, BORDER),
                ]))

                story.append(gallery)

            else:
                story.append(Paragraph(
                    "Tidak ada dokumentasi foto untuk jurnal ini.",
                    styles["ActraceMeta"],
                ))

            # =========================================
            # JOURNAL TIMESTAMPS
            # =========================================

            story.extend([
                Spacer(1, 2 * mm),
                Paragraph(
                    f"Dibuat: "
                    f"{_paragraph(_format_datetime(journal.get('created_at')))}"
                    f" &nbsp;&nbsp;|&nbsp;&nbsp; "
                    f"Diperbarui: "
                    f"{_paragraph(_format_datetime(journal.get('updated_at')))}",
                    styles["ActraceMeta"],
                ),
                HRFlowable(
                    width="100%",
                    thickness=0.5,
                    color=BORDER,
                    spaceBefore=4 * mm,
                    spaceAfter=2 * mm,
                ),
            ])

    # =========================================
    # CLOSING REPORT
    # =========================================

    story.extend([
        Spacer(1, 6 * mm),

        Paragraph(
            "PENUTUP LAPORAN",
            styles["ActraceSection"],
        ),

        Paragraph(
            f"Laporan ini memuat {len(journals)} jurnal kegiatan, "
            f"{len(unique_days)} hari kegiatan tercatat, dan "
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

    # =========================================
    # PAGE HEADER & FOOTER
    # =========================================

    def draw_page(canvas, document):
        canvas.saveState()

        # Header line
        canvas.setStrokeColor(BORDER)
        canvas.setLineWidth(0.55)

        canvas.line(
            left,
            page_height - 15 * mm,
            page_width - right,
            page_height - 15 * mm,
        )

        # Header title
        canvas.setFillColor(NAVY)
        canvas.setFont("Helvetica-Bold", 8)
        canvas.drawString(
            left,
            page_height - 11 * mm,
            "ACTRACE",
        )

        canvas.setFillColor(MUTED)
        canvas.setFont("Helvetica", 7.5)
        canvas.drawRightString(
            page_width - right,
            page_height - 11 * mm,
            "LAPORAN REKAPITULASI JURNAL KEGIATAN",
        )

        # Footer line
        canvas.line(
            left,
            14 * mm,
            page_width - right,
            14 * mm,
        )

        # Footer text
        canvas.drawString(
            left,
            9 * mm,
            "Every Activity Leaves a Trace.",
        )

        canvas.drawRightString(
            page_width - right,
            9 * mm,
            f"Halaman {document.page}",
        )

        canvas.restoreState()

    # =========================================
    # BUILD PDF
    # =========================================

    doc.build(
        story,
        onFirstPage=draw_page,
        onLaterPages=draw_page,
    )

    output.seek(0)

    return output