"""Controle de cargas do ETL: abre e fecha cada carga e registra os arquivos processados."""

import psycopg

STATUS_EM_ANDAMENTO = "em_andamento"
STATUS_CONCLUIDA = "concluida"
STATUS_REPROVADA = "reprovada"
STATUS_ERRO = "erro"
MODOS = ("incremental", "completo")


def iniciar_carga(conexao: psycopg.Connection, fonte: str, modo: str) -> int:
    """Cria a carga e já confirma (commit), para ela sobreviver a uma falha posterior."""
    if modo not in MODOS:
        raise ValueError(f"modo inválido: {modo} (use {', '.join(MODOS)})")
    id_carga = conexao.execute(
        "INSERT INTO etl.cargas (fonte, modo) VALUES (%s, %s) RETURNING id_carga", (fonte, modo)
    ).fetchone()[0]
    conexao.commit()
    return id_carga


def finalizar_carga(
    conexao: psycopg.Connection, id_carga: int, status: str, mensagem: str | None = None
) -> None:
    conexao.execute(
        "UPDATE etl.cargas SET fim = now(), status = %s, mensagem = %s WHERE id_carga = %s",
        (status, mensagem, id_carga),
    )
    conexao.commit()


def registrar_arquivo(conexao: psycopg.Connection, id_carga: int, resultado) -> None:
    conexao.execute(
        "INSERT INTO etl.carga_arquivos (id_carga, entidade, arquivo, hash_arquivo, linhas_lidas,"
        " linhas_ignoradas, situacao) VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (
            id_carga,
            resultado.entidade,
            resultado.arquivo,
            resultado.hash_arquivo,
            resultado.linhas_lidas,
            resultado.linhas_ignoradas,
            resultado.situacao,
        ),
    )


def arquivo_ja_processado(
    conexao: psycopg.Connection, fonte: str, entidade: str, arquivo: str, hash_arquivo: str
) -> bool:
    """True se este mesmo conteúdo já foi levado ao dw com sucesso."""
    linha = conexao.execute(
        "SELECT 1 FROM etl.arquivos_processados"
        " WHERE fonte = %s AND entidade = %s AND arquivo = %s AND hash_arquivo = %s",
        (fonte, entidade, arquivo, hash_arquivo),
    ).fetchone()
    return linha is not None


def confirmar_arquivos(conexao: psycopg.Connection, id_carga: int) -> int:
    """Marca como processados os arquivos da carga (chamar só depois do dw concluído)."""
    cursor = conexao.execute(
        "INSERT INTO etl.arquivos_processados"
        " (fonte, entidade, arquivo, hash_arquivo, id_carga, linhas)"
        " SELECT c.fonte, a.entidade, a.arquivo, a.hash_arquivo, a.id_carga, a.linhas_lidas"
        " FROM etl.carga_arquivos a JOIN etl.cargas c USING (id_carga)"
        " WHERE a.id_carga = %s AND a.situacao = 'carregado'"
        " ON CONFLICT (fonte, entidade, arquivo) DO UPDATE SET"
        "   hash_arquivo = EXCLUDED.hash_arquivo, id_carga = EXCLUDED.id_carga,"
        "   linhas = EXCLUDED.linhas",
        (id_carga,),
    )
    conexao.commit()
    return cursor.rowcount


def linhas_lidas_por_arquivo(conexao: psycopg.Connection, id_carga: int) -> dict[str, int]:
    linhas = conexao.execute(
        "SELECT arquivo, linhas_lidas FROM etl.carga_arquivos WHERE id_carga = %s ORDER BY 1",
        (id_carga,),
    ).fetchall()
    return {arquivo: lidas for arquivo, lidas in linhas}
