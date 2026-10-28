"""Uso: python -m src.gerador   (gera os CSVs em data/raw/ com os parâmetros de src/config.py)."""

from src.gerador.principal import gerar_dados


def _principal() -> None:
    resumo = gerar_dados(progresso=print)
    print("\nLinhas de dados por arquivo:")
    for arquivo, linhas in resumo.linhas_por_arquivo.items():
        print(f"  {arquivo:<28} {linhas:>9,}".replace(",", "."))
    print("\nAnomalias injetadas:", resumo.anomalias_por_tipo)
    print("Problemas de qualidade:", resumo.problemas_por_tipo)
    print(
        f"\nMemória livre: {resumo.memoria_livre_inicio_gb:.2f} GB (início) -> "
        f"{resumo.memoria_livre_fim_gb:.2f} GB (fim) | "
        f"pico do processo: {resumo.pico_memoria_processo_gb:.2f} GB"
    )


if __name__ == "__main__":
    _principal()
