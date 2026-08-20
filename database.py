import os
import sqlite3
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = Path(os.getenv("DATABASE_PATH", str(BASE_DIR / "database.db")))
DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)


MORADORES_EXEMPLO = (
    ("Ana Silva", "101-A", "ana.silva@example.com"),
    ("Bruno Oliveira", "202-B", "bruno.oliveira@example.com"),
    ("Carla Souza", "303-C", "carla.souza@example.com"),
)


def get_connection() -> sqlite3.Connection:
    """Abre uma conexão SQLite com linhas acessíveis como dicionários."""
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_db() -> None:
    """Cria as tabelas e inclui os moradores usados na demonstração."""
    with get_connection() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS moradores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL,
                apartamento TEXT NOT NULL,
                email TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS encomendas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                codigo_identificacao TEXT NOT NULL UNIQUE,
                id_morador INTEGER NOT NULL,
                data_hora_recebimento DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                status TEXT NOT NULL DEFAULT 'Aguardando Retirada',
                data_hora_retirada DATETIME,
                transportadora TEXT,
                email_notificado INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (id_morador) REFERENCES moradores(id)
            );
            """
        )

        # Migração compatível com bancos criados pela primeira versão do protótipo.
        colunas_encomendas = {
            coluna["name"]
            for coluna in connection.execute("PRAGMA table_info(encomendas)").fetchall()
        }
        if "data_hora_retirada" not in colunas_encomendas:
            connection.execute(
                "ALTER TABLE encomendas ADD COLUMN data_hora_retirada DATETIME"
            )
        if "transportadora" not in colunas_encomendas:
            connection.execute("ALTER TABLE encomendas ADD COLUMN transportadora TEXT")
        if "email_notificado" not in colunas_encomendas:
            connection.execute(
                "ALTER TABLE encomendas ADD COLUMN email_notificado INTEGER NOT NULL DEFAULT 0"
            )

        quantidade = connection.execute(
            "SELECT COUNT(*) AS total FROM moradores"
        ).fetchone()["total"]
        if quantidade == 0:
            connection.executemany(
                "INSERT INTO moradores (nome, apartamento, email) VALUES (?, ?, ?)",
                MORADORES_EXEMPLO,
            )


if __name__ == "__main__":
    init_db()
    print(f"Banco inicializado em: {DATABASE_PATH}")
