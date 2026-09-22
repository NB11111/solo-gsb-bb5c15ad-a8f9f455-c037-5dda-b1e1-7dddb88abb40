"""POST /api/v1/stoichiometry/batch 测试。"""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.stoichiometry import compute_stoichiometry, decimal_text

client = TestClient(app)

WATER = {"reactants": ["H2", "O2"], "products": ["H2O"]}


def _post(payload: dict):
    return client.post("/api/v1/stoichiometry/batch", json=payload)


# ------------------------------------------------------------ 核心计算（单元）
def test_compute_stoichiometry_exact_tie():
    result = compute_stoichiometry(
        [2, 1], [2], [Decimal("2"), Decimal("1")]
    )
    assert result.extent == Decimal(1)
    assert [a.limiting for a in result.reactants] == [True, True]
    assert [a.remaining for a in result.reactants] == [Decimal(0), Decimal(0)]
    assert list(result.product_yields) == [Decimal(2)]


def test_compute_stoichiometry_non_terminating_rounds_to_28_digits():
    # 1/3 型：输出按 28 位有效数字正确舍入；可精确表示的结果保持精确
    result = compute_stoichiometry(
        [3, 2], [1, 6], [Decimal("1"), Decimal("1")]
    )
    assert decimal_text(result.extent) == "0.3333333333333333333333333333"
    assert decimal_text(result.reactants[1].consumed) == (
        "0.6666666666666666666666666667"
    )
    assert decimal_text(result.reactants[1].remaining) == (
        "0.3333333333333333333333333333"
    )
    # 6 × 1/3 精确为 2，不出现 1.999…98 之类的舍入伪影
    assert decimal_text(result.product_yields[1]) == "2"


def test_decimal_text_avoids_scientific_notation():
    assert decimal_text(Decimal("1E+3")) == "1000"
    assert decimal_text(Decimal("2.50")) == "2.50"
    assert decimal_text(Decimal(0)) == "0"


# ------------------------------------------------------------ 成功路径
def test_batch_basic_limiting_and_amounts():
    resp = _post({
        **WATER,
        "feeds": [
            {"species": "H2", "moles": "2.5"},
            {"species": "O2", "moles": "1"},
        ],
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["normalized"]["equation"] == "2H2 + O2 -> 2H2O"
    assert data["extent"] == "1"
    assert data["limiting_reactants"] == ["O2"]

    reactants = {item["normalized"]: item for item in data["reactants"]}
    assert reactants["H2"] == {
        "input": "H2",
        "normalized": "H2",
        "coefficient": 2,
        "fed": "2.5",
        "consumed": "2",
        "remaining": "0.5",
        "limiting": False,
    }
    assert reactants["O2"]["consumed"] == "1"
    assert reactants["O2"]["remaining"] == "0"
    assert reactants["O2"]["limiting"] is True

    products = {item["normalized"]: item for item in data["products"]}
    assert products["H2O"]["coefficient"] == 2
    assert products["H2O"]["theoretical_yield"] == "2"


def test_batch_tied_limiting_reactants_all_returned():
    # 化学计量比投料：两种反应物并列限量，全部返回
    resp = _post({
        **WATER,
        "feeds": [
            {"species": "H2", "moles": "2"},
            {"species": "O2", "moles": "1"},
        ],
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["extent"] == "1"
    assert data["limiting_reactants"] == ["H2", "O2"]
    assert all(item["remaining"] == "0" for item in data["reactants"])
    assert all(item["limiting"] for item in data["reactants"])


def test_batch_decimal_strings_have_no_float_error():
    # 0.1 级小数投料：结果必须是精确十进制字符串（如 0.05 而非 0.050000000000000003）
    resp = _post({
        **WATER,
        "feeds": [
            {"species": "H2", "moles": "0.5"},
            {"species": "O2", "moles": "0.3"},
        ],
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["extent"] == "0.25"
    reactants = {item["normalized"]: item for item in data["reactants"]}
    assert reactants["O2"]["consumed"] == "0.25"
    assert reactants["O2"]["remaining"] == "0.05"
    products = {item["normalized"]: item for item in data["products"]}
    assert products["H2O"]["theoretical_yield"] == "0.5"


def test_batch_zero_feed_gives_zero_extent():
    resp = _post({
        **WATER,
        "feeds": [
            {"species": "H2", "moles": "0"},
            {"species": "O2", "moles": "1"},
        ],
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["extent"] == "0"
    assert data["limiting_reactants"] == ["H2"]
    reactants = {item["normalized"]: item for item in data["reactants"]}
    assert reactants["O2"]["remaining"] == "1"
    assert data["products"][0]["theoretical_yield"] == "0"


def test_batch_numeric_moles_accepted():
    # JSON 数字也可传入（精确场景建议用字符串）
    resp = _post({
        **WATER,
        "feeds": [{"species": "H2", "moles": 2}, {"species": "O2", "moles": 1}],
    })
    assert resp.status_code == 200
    assert {item["fed"] for item in resp.json()["reactants"]} == {"2", "1"}


def test_batch_feed_species_equivalent_writing_matches():
    # 投料物种写法与 reactants 不同但规范化后相同：正确对应
    resp = _post({
        "reactants": ["Ca(OH)2", "HCl"],
        "products": ["CaCl2", "H2O"],
        "feeds": [
            {"species": "Ca[OH]2", "moles": "1"},
            {"species": "H Cl", "moles": "2"},
        ],
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["normalized"]["equation"] == "Ca(OH)2 + 2HCl -> CaCl2 + 2H2O"
    assert data["extent"] == "1"
    assert data["limiting_reactants"] == ["Ca(OH)2", "HCl"]


def test_batch_order_independent_identical_result():
    # 反应与投料书写顺序变化：reaction_id 与全部计算结果完全一致
    payload_a = {
        "reactants": ["O2", "H2"],
        "products": ["H2O"],
        "feeds": [
            {"species": "O2", "moles": "1"},
            {"species": "H2", "moles": "2.5"},
        ],
    }
    payload_b = {
        "reactants": ["H2", "O2"],
        "products": ["H2O"],
        "feeds": [
            {"species": "H2", "moles": "2.5"},
            {"species": "O2", "moles": "1"},
        ],
    }
    r1, r2 = _post(payload_a), _post(payload_b)
    assert r1.status_code == r2.status_code == 200
    assert r1.json() == r2.json()


def test_batch_reaction_id_matches_balance_endpoint():
    balance = client.post("/api/v1/balance", json=WATER).json()
    batch = _post({
        **WATER,
        "feeds": [
            {"species": "H2", "moles": "2"},
            {"species": "O2", "moles": "1"},
        ],
    }).json()
    assert balance["reaction_id"] == batch["reaction_id"]


# ------------------------------------------------------------ 结构化错误
def test_batch_missing_feed_species():
    resp = _post({**WATER, "feeds": [{"species": "H2", "moles": "1"}]})
    assert resp.status_code == 422
    body = resp.json()
    assert body["error"]["code"] == "INVALID_REQUEST"
    assert body["error"]["details"]["missing_species"] == ["O2"]
    assert "reaction_id" in body


def test_batch_empty_feeds_reports_all_missing():
    resp = _post({**WATER, "feeds": []})
    assert resp.status_code == 422
    assert resp.json()["error"]["details"]["missing_species"] == ["H2", "O2"]


def test_batch_unknown_feed_species():
    resp = _post({
        **WATER,
        "feeds": [
            {"species": "H2", "moles": "1"},
            {"species": "O2", "moles": "1"},
            {"species": "CO2", "moles": "1"},
        ],
    })
    assert resp.status_code == 422
    body = resp.json()
    assert body["error"]["code"] == "INVALID_REQUEST"
    assert body["error"]["details"]["unknown_species"] == ["CO2"]


def test_batch_duplicate_feed_species():
    resp = _post({
        **WATER,
        "feeds": [
            {"species": "H2", "moles": "1"},
            {"species": "[H2]", "moles": "2"},
            {"species": "O2", "moles": "1"},
        ],
    })
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "DUPLICATE_SPECIES"


def test_batch_feed_formula_parse_error():
    resp = _post({
        **WATER,
        "feeds": [
            {"species": "Xx", "moles": "1"},
            {"species": "O2", "moles": "1"},
        ],
    })
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "FORMULA_PARSE_ERROR"


def test_batch_non_unique_balance():
    resp = _post({
        "reactants": ["C", "O2"],
        "products": ["CO", "CO2"],
        "feeds": [
            {"species": "C", "moles": "1"},
            {"species": "O2", "moles": "1"},
        ],
    })
    assert resp.status_code == 422
    body = resp.json()
    assert body["error"]["code"] == "NON_UNIQUE_BALANCE"
    assert "reaction_id" in body


def test_batch_impossible_balance():
    resp = _post({
        "reactants": ["H2O"],
        "products": ["Au"],
        "feeds": [{"species": "H2O", "moles": "1"}],
    })
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "IMPOSSIBLE_BALANCE"


def test_batch_reaction_formula_parse_error():
    resp = _post({
        "reactants": ["Xx"],
        "products": ["H2O"],
        "feeds": [{"species": "Xx", "moles": "1"}],
    })
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "FORMULA_PARSE_ERROR"


@pytest.mark.parametrize("moles", ["-1", "NaN", "Infinity", "-Infinity", "abc"])
def test_batch_invalid_moles_rejected(moles):
    resp = _post({
        **WATER,
        "feeds": [
            {"species": "H2", "moles": moles},
            {"species": "O2", "moles": "1"},
        ],
    })
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "INVALID_REQUEST"


def test_batch_missing_feeds_field():
    resp = _post(WATER)
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "INVALID_REQUEST"
