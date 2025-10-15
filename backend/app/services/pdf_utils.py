import fitz  # PyMuPDF
import os

def pdf_to_images_pymupdf(pdf_path, output_folder="output_images", dpi=200, fmt="png"):
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)

    doc = fitz.open(pdf_path)
    image_paths = []

    for i, page in enumerate(doc):
        # Render page to a pixmap
        zoom = dpi / 72  # 72 dpi is default
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat)

        image_path = os.path.join(output_folder, f"page_{i+1}.{fmt}")
        pix.save(image_path)
        image_paths.append(image_path)

    return image_paths
