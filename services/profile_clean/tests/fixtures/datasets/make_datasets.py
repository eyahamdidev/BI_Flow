"""Generate cross-dataset safety fixtures (offline, committed)."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path(__file__).parent


def titanic() -> pd.DataFrame:
    rng = np.random.default_rng(42)
    n = 891
    age = rng.uniform(1, 70, n)
    age[rng.choice(n, 177, replace=False)] = np.nan
    cabin = np.array([f"C{i % 50}" if i % 4 else np.nan for i in range(n)], dtype=object)
    cabin[rng.choice(n, 687, replace=False)] = np.nan
    embarked = pd.Series(rng.choice(["S", "C", "Q"], n), dtype="string")
    embarked.iloc[rng.choice(n, 2, replace=False)] = pd.NA
    tickets = [f"A/{rng.integers(1000,9999)}" if i % 3 else str(rng.integers(10000, 99999)) for i in range(n)]
    fare = np.clip(rng.uniform(7, 200, n), 7, 200)
    fare[rng.choice(n, 15, replace=False)] = rng.uniform(300, 512, 15)
    return pd.DataFrame(
        {
            "PassengerId": np.arange(1, n + 1),
            "Survived": rng.integers(0, 2, n),
            "Pclass": rng.choice([1, 2, 3], n),
            "Name": [f"Person {i}" for i in range(n)],
            "Sex": rng.choice(["male", "female"], n),
            "Age": age,
            "SibSp": rng.integers(0, 5, n),
            "Parch": rng.integers(0, 4, n),
            "Ticket": tickets,
            "Fare": fare,
            "Cabin": cabin,
            "Embarked": embarked,
        }
    )


def iris() -> pd.DataFrame:
    from sklearn.datasets import load_iris

    data = load_iris(as_frame=True)
    df = data.frame.rename(
        columns={
            "sepal length (cm)": "sepal.length",
            "sepal width (cm)": "sepal.width",
            "petal length (cm)": "petal.length",
            "petal width (cm)": "petal.width",
            "target": "variety",
        }
    )
    df["variety"] = df["variety"].map({0: "setosa", 1: "versicolor", 2: "virginica"})
    row = df.iloc[0].copy()
    return pd.concat([df, row.to_frame().T], ignore_index=True)


def cafe_dirty() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "order_id": ["a1", "a2", "a3"],
            "amount": ["10.5", "ERROR", "12"],
            "status": ["OK", "UNKNOWN", "OK"],
            "when": ["2024-01-01", "bad", "15/03/2024"],
        }
    )


def hotel_dirty() -> pd.DataFrame:
    rows = []
    for i in range(40):
        rows.append(
            {
                "booking_id": f"b{i}",
                "agent": "NULL" if i % 5 == 0 else f"ag{i % 3}",
                "adr": -10.0 if i == 7 else (9999.0 if i == 8 else 100.0),
            }
        )
    for i in range(10):
        rows.append(rows[i].copy())
    return pd.DataFrame(rows)


def parent_child() -> tuple[pd.DataFrame, pd.DataFrame]:
    cust = pd.DataFrame({"customer_id": ["c1", "c2"], "name": ["Ann", "Bob"]})
    orders = pd.DataFrame({"order_id": ["o1", "o2"], "customer_id": ["c1", "c99"]})
    return cust, orders


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    titanic().to_csv(OUT / "titanic.csv", index=False)
    iris().to_csv(OUT / "iris.csv", index=False)
    cafe_dirty().to_csv(OUT / "cafe_dirty.csv", index=False)
    hotel_dirty().to_csv(OUT / "hotel_dirty.csv", index=False)
    c, o = parent_child()
    c.to_csv(OUT / "parent.csv", index=False)
    o.to_csv(OUT / "child.csv", index=False)
    pd.DataFrame({"id": [1], "zip": ["01310"], "flag": [1]}).to_csv(OUT / "edge_mixed.csv", index=False)
    pd.DataFrame({"x": [1, 1, 1]}).to_csv(OUT / "edge_constant.csv", index=False)
    pd.DataFrame({"a": [None, None]}).to_csv(OUT / "edge_all_null.csv", index=False)
    (OUT / "edge_empty.csv").write_text("", encoding="utf-8")
    (OUT / "edge_header_only.csv").write_text("a,b\n", encoding="utf-8")
    print(f"Wrote datasets to {OUT}")


if __name__ == "__main__":
    main()
