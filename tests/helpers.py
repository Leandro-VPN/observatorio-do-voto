import csv

from auditabr.acquisition import preserve_asset

HEADER = "ANO_ELEICAO NR_TURNO SG_UF CD_MUNICIPIO NM_MUNICIPIO NR_ZONA NR_SECAO CD_CARGO DS_CARGO QT_APTOS QT_COMPARECIMENTO QT_ABSTENCOES QT_VOTOS_NOMINAIS QT_VOTOS_BRANCOS QT_VOTOS_NULOS QT_VOTOS_ANULADOS_APU_SEP NR_LOCAL_VOTACAO".split()


def synthetic_asset(root, rows, header=HEADER, name="test.csv"):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.writer(stream, delimiter=";")
        writer.writerow(header)
        writer.writerows(rows)
    return preserve_asset(root, path, {"id": "SYNTHETIC", "dataset_id": "SYNTHETIC", "url": "synthetic://fixture"})


def turnout_rows():
    return [
        [2022, 1, "MA", "00001", "Município teste", "1", "1", "1", "Presidente", 400, 300, 100, 280, 10, 10, 0, 10],
        [2022, 1, "MA", "00001", "Município teste", "1", "1", "3", "Governador", 400, 300, 100, 280, 10, 10, 0, 10],
        [2022, 1, "MA", "00001", "Município teste", "1", "2", "1", "Presidente", 100, 90, 10, 80, 5, 5, 0, 10],
    ]
