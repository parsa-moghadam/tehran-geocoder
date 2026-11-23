from backend.matcher import Matcher


def test_house_number_from_parsed_fields():
    assert Matcher._house_number({"fields": {"number": "۱۲"}}, "") == "12"


def test_house_number_from_raw_query():
    assert Matcher._house_number({"fields": {}}, "تهران خیابان اکبری پلاک ۱۲") == "12"
    assert Matcher._house_number({"fields": {}}, "اکبری ۱۲") == "12"
    assert Matcher._house_number({"fields": {}}, "منطقه ۲ خیابان اکبری") == ""


def test_number_score():
    assert Matcher._number_score("12", "12") == 100
    assert Matcher._number_score("12", "13") > Matcher._number_score("12", "90")
