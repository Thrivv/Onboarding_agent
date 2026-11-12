import os
from typing import Tuple


def get_file_extension(file_path: str) -> str:
    return os.path.splitext(file_path)[1].lower()


def is_pdf_file(file_path: str) -> bool:
    return get_file_extension(file_path) == '.pdf'


def is_jpeg_file(file_path: str) -> bool:
    ext = get_file_extension(file_path)
    return ext in ['.jpg', '.jpeg']


def is_png_file(file_path: str) -> bool:
    return get_file_extension(file_path) == '.png'


def is_image_file(file_path: str) -> bool:
    ext = get_file_extension(file_path)
    return ext in ['.jpg', '.jpeg', '.png']


def is_supported_file(file_path: str) -> bool:
    ext = get_file_extension(file_path)
    return ext in ['.jpg', '.jpeg', '.png', '.pdf']


def get_file_type_info(file_path: str) -> Tuple[bool, bool, bool, bool]:
    ext = get_file_extension(file_path)
    is_pdf = ext == '.pdf'
    is_jpeg = ext in ['.jpg', '.jpeg']
    is_png = ext == '.png'
    is_image = is_jpeg or is_png
    return is_pdf, is_jpeg, is_png, is_image


def get_evidence_file_extension(file_path: str) -> str:
    ext = get_file_extension(file_path)
    if ext in ['.jpg', '.jpeg', '.png']:
        return ext if ext == '.png' else '.jpg'
    return '.jpg'

