import pytest

from src import banco, config, memoria


def test_url_usa_driver_psycopg_e_escapa_senha():
    url = banco.montar_url("localhost", 5432, "lojas_ipe_dw", "lojas_ipe", "p@ss:w/rd")
    assert url.drivername == "postgresql+psycopg"
    assert url.password == "p@ss:w/rd"
    texto = url.render_as_string(hide_password=False)
    assert texto.startswith("postgresql+psycopg://lojas_ipe:")
    assert "p@ss:w/rd" not in texto  # caracteres especiais ficam escapados na URL


def test_url_do_ambiente_exige_variaveis(monkeypatch):
    monkeypatch.setattr(banco, "load_dotenv", lambda: None)
    for var in (config.VAR_BD_NOME, config.VAR_BD_USUARIO, config.VAR_BD_SENHA):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(RuntimeError, match="BD_NOME"):
        banco.url_do_ambiente()


def test_url_do_ambiente_le_variaveis(monkeypatch):
    monkeypatch.setattr(banco, "load_dotenv", lambda: None)
    monkeypatch.setenv(config.VAR_BD_SERVIDOR, "servidor.teste")
    monkeypatch.setenv(config.VAR_BD_PORTA, "5433")
    monkeypatch.setenv(config.VAR_BD_NOME, "banco_teste")
    monkeypatch.setenv(config.VAR_BD_USUARIO, "usuario_teste")
    monkeypatch.setenv(config.VAR_BD_SENHA, "senha_teste")
    url = banco.url_do_ambiente()
    assert (url.host, url.port, url.database, url.username) == (
        "servidor.teste",
        5433,
        "banco_teste",
        "usuario_teste",
    )


def test_scripts_ddl_em_ordem_e_sem_o_administrativo():
    nomes = [p.name for p in banco.scripts_ddl()]
    assert nomes == sorted(nomes)
    assert nomes[0] == "01_schemas.sql"
    assert not any(n.startswith(config.PREFIXO_SCRIPT_ADMIN) for n in nomes)


def test_memoria_insuficiente_bloqueia(monkeypatch):
    monkeypatch.setattr(memoria, "memoria_livre_gb", lambda: 0.1)
    with pytest.raises(memoria.MemoriaInsuficiente):
        memoria.verificar_memoria_livre()


def test_memoria_suficiente_libera(monkeypatch):
    monkeypatch.setattr(memoria, "memoria_livre_gb", lambda: 1.5)
    assert memoria.verificar_memoria_livre() == 1.5
