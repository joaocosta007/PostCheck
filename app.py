import json
import os
import re
import smtplib
import sqlite3
import unicodedata
from datetime import datetime
from email.message import EmailMessage
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

from flask import Flask, jsonify, render_template, request
from dotenv import load_dotenv

from database import get_connection, init_db
from pivic_processing import processar_imagem


load_dotenv()
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024
EXTENSOES_PERMITIDAS = {"png", "jpg", "jpeg", "webp", "bmp", "tif", "tiff"}


def normalizar(texto: str) -> str:
    sem_acentos = "".join(
        caractere
        for caractere in unicodedata.normalize("NFD", texto.casefold())
        if unicodedata.category(caractere) != "Mn"
    )
    return re.sub(r"[^a-z0-9]+", " ", sem_acentos).strip()


def encontrar_morador(texto_ocr: str):
    texto_normalizado = normalizar(texto_ocr)
    with get_connection() as connection:
        moradores = connection.execute(
            "SELECT id, nome, apartamento, email FROM moradores ORDER BY nome"
        ).fetchall()

    for morador in moradores:
        nome = normalizar(morador["nome"])
        partes = [parte for parte in nome.split() if len(parte) >= 3]
        if nome in texto_normalizado or (
            len(partes) >= 2 and all(parte in texto_normalizado for parte in partes)
        ):
            return dict(morador)
    return None


def gerar_codigo() -> str:
    instante = datetime.now().strftime("%Y%m%d%H%M%S")
    return f"ENC-{instante}-{uuid4().hex[:6].upper()}"


def detectar_transportadora(texto_ocr: str) -> str:
    texto = normalizar(texto_ocr)
    transportadoras = {
        "correios": "Correios",
        "jadlog": "Jadlog",
        "dhl": "DHL",
        "fedex": "FedEx",
        "ups": "UPS",
        "loggi": "Loggi",
        "total express": "Total Express",
        "mercado livre": "Mercado Livre",
        "amazon": "Amazon Logistics",
        "shopee": "Shopee Express",
    }
    for termo, nome in transportadoras.items():
        if termo in texto:
            return nome
    return "Não identificada"


def enviar_email(destinatario: str, nome: str, codigo: str) -> tuple[bool, str]:
    usar_resend = os.getenv("EMAIL_PROVIDER", "").lower() == "resend" or bool(
        os.getenv("RESEND_API_KEY")
    )
    destinatario_original = destinatario
    corpo = (
        f"Olá, {nome}!\n\n"
        "Uma encomenda sua chegou à portaria.\n"
        f"Código de retirada: {codigo}\n\n"
        "Apresente este código ao retirar o pacote."
    )

    if usar_resend:
        chave = os.getenv("RESEND_API_KEY")
        remetente = os.getenv("RESEND_FROM", "onboarding@resend.dev")
        destinatario = os.getenv("RESEND_TEST_RECIPIENT", destinatario)
        if not chave:
            return False, "RESEND_API_KEY não configurada; e-mail não enviado."
        if destinatario != destinatario_original:
            corpo += f"\n\nModo de demonstração: destinatário original {destinatario_original}."

        requisicao = Request(
            "https://api.resend.com/emails",
            data=json.dumps(
                {
                    "from": f"PostCheck <{remetente}>",
                    "to": [destinatario],
                    "subject": "Sua encomenda chegou",
                    "text": corpo,
                }
            ).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {chave}",
                "Content-Type": "application/json",
                "User-Agent": "PostCheck/1.0",
            },
            method="POST",
        )
        try:
            with urlopen(requisicao, timeout=15) as resposta:
                if not 200 <= resposta.status < 300:
                    return False, f"Resend recusou o envio (HTTP {resposta.status})."
            detalhe = "E-mail enviado com sucesso pelo Resend."
            if destinatario != destinatario_original:
                detalhe += f" Modo de teste: enviado para {destinatario}."
            return True, detalhe
        except HTTPError as erro:
            try:
                resposta_erro = json.loads(erro.read().decode("utf-8"))
                motivo = resposta_erro.get("message", str(erro))
            except (ValueError, UnicodeDecodeError):
                motivo = str(erro)
            return False, f"Encomenda registrada, mas o Resend recusou o e-mail: {motivo}"
        except (OSError, URLError) as erro:
            return False, f"Encomenda registrada, mas o Resend não pôde ser acessado: {erro}"

    servidor = os.getenv("SMTP_HOST")
    remetente = os.getenv("SMTP_FROM")
    porta = int(os.getenv("SMTP_PORT", "587"))
    usuario = os.getenv("SMTP_USER")
    senha = os.getenv("SMTP_PASSWORD")
    usar_tls = os.getenv("SMTP_USE_TLS", "true").lower() in {"1", "true", "yes", "sim"}

    if not servidor or not remetente:
        return False, "SMTP não configurado; a encomenda foi registrada sem notificação."

    mensagem = EmailMessage()
    mensagem["Subject"] = "Sua encomenda chegou"
    mensagem["From"] = remetente
    mensagem["To"] = destinatario
    mensagem.set_content(corpo)

    try:
        with smtplib.SMTP(servidor, porta, timeout=15) as smtp:
            if usar_tls:
                smtp.starttls()
            if usuario and senha:
                smtp.login(usuario, senha)
            smtp.send_message(mensagem)
        return True, "E-mail enviado com sucesso."
    except (OSError, smtplib.SMTPException) as erro:
        return False, f"Encomenda registrada, mas o e-mail falhou: {erro}"


def validar_morador(dados: dict):
    nome = str(dados.get("nome", "")).strip()
    apartamento = str(dados.get("apartamento", "")).strip()
    email = str(dados.get("email", "")).strip().lower()
    if not nome or not apartamento or not email:
        return None, "Nome, apartamento e e-mail são obrigatórios."
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        return None, "Informe um endereço de e-mail válido."
    return {"nome": nome, "apartamento": apartamento, "email": email}, None


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/health")
def health():
    try:
        with get_connection() as connection:
            connection.execute("SELECT 1").fetchone()
        return jsonify({"status": "ok"})
    except sqlite3.Error:
        return jsonify({"status": "error", "componente": "database"}), 503


@app.get("/api/moradores")
def listar_moradores():
    termo = request.args.get("q", "").strip()
    parametros = []
    filtro = ""
    if termo:
        busca = f"%{termo}%"
        filtro = "WHERE nome LIKE ? COLLATE NOCASE OR apartamento LIKE ? COLLATE NOCASE OR email LIKE ? COLLATE NOCASE"
        parametros = [busca, busca, busca]
    with get_connection() as connection:
        moradores = connection.execute(
            f"""
            SELECT m.id, m.nome, m.apartamento, m.email,
                   COUNT(e.id) AS total_encomendas
            FROM moradores m
            LEFT JOIN encomendas e ON e.id_morador = m.id
            {filtro}
            GROUP BY m.id, m.nome, m.apartamento, m.email
            ORDER BY m.nome
            """,
            parametros,
        ).fetchall()
    return jsonify([dict(morador) for morador in moradores])


@app.post("/api/moradores")
def criar_morador():
    dados, erro = validar_morador(request.get_json(silent=True) or {})
    if erro:
        return jsonify({"erro": erro}), 400
    with get_connection() as connection:
        cursor = connection.execute(
            "INSERT INTO moradores (nome, apartamento, email) VALUES (?, ?, ?)",
            (dados["nome"], dados["apartamento"], dados["email"]),
        )
    return jsonify({"id": cursor.lastrowid, **dados, "total_encomendas": 0}), 201


@app.put("/api/moradores/<int:id_morador>")
def atualizar_morador(id_morador: int):
    dados, erro = validar_morador(request.get_json(silent=True) or {})
    if erro:
        return jsonify({"erro": erro}), 400
    with get_connection() as connection:
        existe = connection.execute(
            "SELECT id FROM moradores WHERE id = ?", (id_morador,)
        ).fetchone()
        if existe is None:
            return jsonify({"erro": "Morador não encontrado."}), 404
        connection.execute(
            "UPDATE moradores SET nome = ?, apartamento = ?, email = ? WHERE id = ?",
            (dados["nome"], dados["apartamento"], dados["email"], id_morador),
        )
    return jsonify({"id": id_morador, **dados})


@app.delete("/api/moradores/<int:id_morador>")
def excluir_morador(id_morador: int):
    with get_connection() as connection:
        morador = connection.execute(
            """
            SELECT m.id, COUNT(e.id) AS total_encomendas
            FROM moradores m
            LEFT JOIN encomendas e ON e.id_morador = m.id
            WHERE m.id = ?
            GROUP BY m.id
            """,
            (id_morador,),
        ).fetchone()
        if morador is None:
            return jsonify({"erro": "Morador não encontrado."}), 404
        if morador["total_encomendas"]:
            return jsonify(
                {"erro": "Este morador possui encomendas vinculadas e não pode ser excluído."}
            ), 409
        connection.execute("DELETE FROM moradores WHERE id = ?", (id_morador,))
    return jsonify({"mensagem": "Morador excluído com sucesso."})


@app.post("/api/scan")
def scan():
    arquivo = request.files.get("imagem")
    if arquivo is None or not arquivo.filename:
        return jsonify({"erro": "Envie uma imagem no campo 'imagem'."}), 400

    extensao = arquivo.filename.rsplit(".", 1)[-1].lower() if "." in arquivo.filename else ""
    if extensao not in EXTENSOES_PERMITIDAS:
        return jsonify({"erro": "Formato de imagem não permitido."}), 400

    try:
        texto, caminho = processar_imagem(arquivo)
    except ValueError as erro:
        return jsonify({"erro": str(erro)}), 400
    except Exception as erro:
        app.logger.exception("Falha no processamento da imagem")
        return jsonify({"erro": f"Falha ao processar a imagem: {erro}"}), 500

    morador = encontrar_morador(texto)
    return jsonify(
        {
            "nome_detectado": texto,
            "morador_encontrado": morador,
            "codigo_gerado": gerar_codigo(),
            "imagem_processada_path": caminho,
            "transportadora_detectada": detectar_transportadora(texto),
        }
    )


@app.post("/api/confirmar")
def confirmar():
    dados = request.get_json(silent=True) or {}
    id_morador = dados.get("id_morador")
    codigo = str(dados.get("codigo_identificacao", "")).strip()
    transportadora = str(dados.get("transportadora", "Não identificada")).strip()
    if not id_morador or not codigo:
        return jsonify({"erro": "id_morador e codigo_identificacao são obrigatórios."}), 400

    with get_connection() as connection:
        morador = connection.execute(
            "SELECT id, nome, apartamento, email FROM moradores WHERE id = ?",
            (id_morador,),
        ).fetchone()
        if morador is None:
            return jsonify({"erro": "Morador não encontrado."}), 404

        try:
            cursor = connection.execute(
                """
                INSERT INTO encomendas
                    (codigo_identificacao, id_morador, data_hora_recebimento,
                     status, transportadora, email_notificado)
                VALUES (?, ?, ?, ?, ?, 0)
                """,
                (
                    codigo,
                    id_morador,
                    datetime.now().isoformat(timespec="seconds"),
                    "Aguardando Retirada",
                    transportadora or "Não identificada",
                ),
            )
        except sqlite3.IntegrityError:
            return jsonify({"erro": "Este código de identificação já foi registrado."}), 409

    email_enviado, mensagem_email = enviar_email(
        morador["email"], morador["nome"], codigo
    )
    if email_enviado:
        with get_connection() as connection:
            connection.execute(
                "UPDATE encomendas SET email_notificado = 1 WHERE id = ?",
                (cursor.lastrowid,),
            )
    return jsonify(
        {
            "mensagem": "Encomenda registrada com sucesso.",
            "id_encomenda": cursor.lastrowid,
            "email_enviado": email_enviado,
            "detalhe_email": mensagem_email,
        }
    ), 201


@app.get("/api/encomendas")
def listar_encomendas():
    termo = request.args.get("q", "").strip()
    filtro = ""
    parametros = []
    if termo:
        filtro = """
            WHERE e.codigo_identificacao LIKE ? COLLATE NOCASE
               OR m.nome LIKE ? COLLATE NOCASE
               OR m.apartamento LIKE ? COLLATE NOCASE
               OR e.data_hora_recebimento LIKE ? COLLATE NOCASE
               OR COALESCE(e.data_hora_retirada, '') LIKE ? COLLATE NOCASE
               OR e.status LIKE ? COLLATE NOCASE
               OR COALESCE(e.transportadora, '') LIKE ? COLLATE NOCASE
        """
        busca = f"%{termo}%"
        parametros = [busca] * 7

    with get_connection() as connection:
        registros = connection.execute(
            f"""
            SELECT e.id, e.codigo_identificacao, m.nome AS morador,
                   m.apartamento, e.data_hora_recebimento, e.status,
                   e.data_hora_retirada,
                   COALESCE(e.transportadora, 'Não identificada') AS transportadora,
                   e.email_notificado
            FROM encomendas e
            JOIN moradores m ON m.id = e.id_morador
            {filtro}
            ORDER BY e.data_hora_recebimento DESC, e.id DESC
            """,
            parametros,
        ).fetchall()
    return jsonify([dict(registro) for registro in registros])


@app.get("/api/resumo")
def resumo():
    inicio_semana = datetime.now().date().isoformat()
    with get_connection() as connection:
        metricas = connection.execute(
            """
            SELECT COUNT(*) AS total,
                   SUM(CASE WHEN status = 'Aguardando Retirada' THEN 1 ELSE 0 END) AS aguardando,
                   SUM(CASE WHEN status = 'Aguardando Retirada' AND email_notificado = 0 THEN 1 ELSE 0 END) AS notificacoes_pendentes,
                   SUM(CASE WHEN status = 'Entregue' AND date(data_hora_retirada) >= date(?, 'weekday 0', '-6 days') THEN 1 ELSE 0 END) AS entregues_semana
            FROM encomendas
            """,
            (inicio_semana,),
        ).fetchone()
    return jsonify({chave: int(metricas[chave] or 0) for chave in metricas.keys()})


@app.patch("/api/encomendas/<int:id_encomenda>/retirada")
def registrar_retirada(id_encomenda: int):
    data_retirada = datetime.now().isoformat(timespec="seconds")
    with get_connection() as connection:
        encomenda = connection.execute(
            "SELECT id, status FROM encomendas WHERE id = ?", (id_encomenda,)
        ).fetchone()
        if encomenda is None:
            return jsonify({"erro": "Encomenda não encontrada."}), 404
        if encomenda["status"] == "Entregue":
            return jsonify({"erro": "Esta encomenda já teve a retirada registrada."}), 409

        connection.execute(
            """
            UPDATE encomendas
            SET status = 'Entregue', data_hora_retirada = ?
            WHERE id = ?
            """,
            (data_retirada, id_encomenda),
        )

    return jsonify(
        {
            "mensagem": "Retirada registrada com sucesso.",
            "status": "Entregue",
            "data_hora_retirada": data_retirada,
        }
    )


@app.errorhandler(413)
def arquivo_grande(_erro):
    return jsonify({"erro": "A imagem excede o limite de 10 MB."}), 413


init_db()


if __name__ == "__main__":
    app.run(debug=True, port=int(os.getenv("APP_PORT", "5001")))
