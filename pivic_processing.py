from pathlib import Path
from typing import Union
from uuid import uuid4

import cv2
import numpy as np
import pytesseract
from werkzeug.datastructures import FileStorage


BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "static" / "uploads"


def processar_imagem(arquivo: Union[FileStorage, bytes]) -> tuple[str, str]:
    """Pré-processa uma etiqueta, executa OCR e retorna texto e URL da imagem."""
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    conteudo = arquivo.read() if hasattr(arquivo, "read") else arquivo
    if not conteudo:
        raise ValueError("O arquivo de imagem está vazio.")

    dados = np.frombuffer(conteudo, dtype=np.uint8)
    imagem = cv2.imdecode(dados, cv2.IMREAD_COLOR)
    if imagem is None:
        raise ValueError("Não foi possível decodificar a imagem enviada.")

    cinza = cv2.cvtColor(imagem, cv2.COLOR_BGR2GRAY)
    suavizada = cv2.GaussianBlur(cinza, (5, 5), 0)
    _, binarizada = cv2.threshold(
        suavizada, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
    )

    nome_arquivo = f"processada_{uuid4().hex[:12]}.png"
    caminho_saida = UPLOAD_DIR / nome_arquivo
    if not cv2.imwrite(str(caminho_saida), binarizada):
        raise OSError("Não foi possível salvar a imagem processada.")

    texto = pytesseract.image_to_string(binarizada, lang="por")
    texto_limpo = " ".join(texto.split())
    return texto_limpo, f"/static/uploads/{nome_arquivo}"
