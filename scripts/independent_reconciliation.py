"""Second implementation: Arrow CSV aggregation compared against published DuckDB."""
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as csv

from auditabr.domain import election_date
from auditabr.storage import current_manifest, reader
from auditabr.utils import read_json, utcnow, write_json

root = Path("storage")
snapshot = current_manifest(root)["snapshot_id"]
checks = []
fields = {"SG_UF": pa.string(), "CD_CARGO": pa.int64(), "NR_TURNO": pa.int64(),
          "DT_ELEICAO": pa.string(), "QT_APTOS": pa.int64(), "QT_COMPARECIMENTO": pa.int64(),
          "QT_ABSTENCOES": pa.int64()}
for year, uf in ((2022, "MA"), (2024, "AC")):
    source_scope = "BR" if year % 4 == 2 else uf
    receipt = read_json(root / "cache" / f"acquired-{year}-{source_scope}-turnout.json")
    totals = {r: [0, 0, 0, 0] for r in (1, 2)}
    stream = csv.open_csv(receipt["path"], read_options=csv.ReadOptions(encoding="latin1", block_size=8*1024**2),
                          parse_options=csv.ParseOptions(delimiter=";"),
                          convert_options=csv.ConvertOptions(include_columns=list(fields), column_types=fields))
    for batch in stream:
        for turn in (1, 2):
            mask = pc.and_(pc.equal(batch["SG_UF"], uf), pc.equal(batch["NR_TURNO"], turn))
            mask = pc.and_(mask, pc.equal(batch["CD_CARGO"], 1 if year % 4 == 2 else 11))
            mask = pc.and_(mask, pc.equal(batch["DT_ELEICAO"], election_date(year, turn).strftime("%d/%m/%Y")))
            selected = batch.filter(mask)
            totals[turn][0] += selected.num_rows
            for index, field in enumerate(("QT_APTOS", "QT_COMPARECIMENTO", "QT_ABSTENCOES"), 1):
                totals[turn][index] += pc.sum(selected[field]).as_py() or 0
    with reader(root, snapshot) as db:
        for turn in (1, 2):
            observed = db.execute("""SELECT count(*),coalesce(sum(eligible),0),coalesce(sum(present),0),
                coalesce(sum(absent),0) FROM section_turnout WHERE year=? AND round=? AND uf=?""", [year, turn, uf]).fetchone()
            checks.append({"year": year, "round": turn, "uf": uf, "raw_arrow": totals[turn],
                           "published_duckdb": list(observed), "equal": totals[turn] == list(observed),
                           "asset_sha256": receipt["sha256"]})
write_json(root / "manifests" / "independent-reconciliation.json",
           {"at": utcnow(), "snapshot_id": snapshot, "columns": ["sections", "eligible", "present", "absent"], "checks": checks})
assert all(check["equal"] for check in checks), checks
print(f"{len(checks)} agregações independentes iguais ao snapshot {snapshot}")
