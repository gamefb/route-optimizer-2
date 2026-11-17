from app.parsing import apply_layout, clean_zip, detect_layout, norm_key, split_rows, street_similarity

PASTE = (
    "12 Oak Street\tApt 4\tSpringfield\tIL\t62701\n"
    "305 N Main St\t\tSpringfield\tIL\t62702\n"
    "77 Elm Avenue\t#2B\tChatham\tIL\t62629\n"
    "9 Pine Rd\t\tNew Berlin\tIL\t62670\n"
)


def test_split_rows_keeps_empty_unit_cells():
    rows = split_rows(PASTE)
    assert len(rows) == 4
    assert all(len(r) == 5 for r in rows)
    assert rows[1][1] == ""


def test_detect_layout_without_header():
    assert detect_layout(split_rows(PASTE)) == ["street", "unit", "city", "state", "zip"]


def test_detect_layout_other_order_and_extra_column():
    text = "62701\tIL\tSpringfield\t12 Oak St\tApt 1\tLeave at door\n62702\tIL\tSpringfield\t40 Main St\t\tCall first\n"
    layout = detect_layout(split_rows(text))
    assert layout[:4] == ["zip", "state", "city", "street"]
    assert layout[4] == "unit"
    assert layout[5] == "extra"
    fields = apply_layout(split_rows(text)[0], layout)
    assert fields["street"] == "12 Oak St" and fields["unit"] == "Apt 1"
    assert fields["extras"] == ["Leave at door"]


def test_all_units_blank_still_finds_unit_column():
    text = "12 Oak St\t\tSpringfield\tIL\t62701\n40 Main St\t\tSpringfield\tIL\t62702\n"
    assert detect_layout(split_rows(text)) == ["street", "unit", "city", "state", "zip"]


def test_zip_leading_zero_restored():
    assert clean_zip("2134") == "02134"
    assert clean_zip("02134-1001") == "02134-1001"
    assert clean_zip("62701.0") == "62701"


def test_norm_key_ignores_spelling_differences():
    a = norm_key("12 Oak Street", "Apt 4", "62701")
    b = norm_key("12 oak st.", "#4", "62701-1234")
    c = norm_key("12 Oak St", "Unit 5", "62701")
    assert a == b
    assert a != c


def test_street_similarity_needs_same_house_number():
    assert street_similarity("12 Oak St", "12 Oaks St") > 0.8
    assert street_similarity("12 Oak St", "14 Oak St") == 0.0
