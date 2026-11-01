"""Game rules and input cleaning that don't need a running server."""

import packs
import utils


# --- client input --------------------------------------------------------


def test_clean_categories_trims_dedupes_and_caps():
    raw = ["  Movie ", "Movie", "", 42, "x" * 50] + [f"C{i}" for i in range(10)]
    cleaned = utils.clean_categories(raw)
    assert cleaned[0] == "Movie"
    assert cleaned.count("Movie") == 1
    assert len(cleaned[1]) == utils.MAX_CATEGORY_LEN
    assert len(cleaned) == utils.MAX_CATEGORIES


def test_clean_categories_falls_back_to_classic():
    assert utils.clean_categories(None) is None
    assert utils.clean_categories("Name") is None
    assert utils.clean_categories(["", "   "]) is None


def test_clean_letters_keeps_only_distinct_a_to_z():
    assert utils.clean_letters("b<img>Lp b") == "BIMGLP"
    assert utils.clean_letters("123") is None
    assert utils.clean_letters(["A"]) is None


def test_clean_answers_keeps_room_categories_and_short_strings():
    answers = {"Name": "Bisi", "Animal": 5, "Hacked": "x", "Thing": "y" * 100}
    cleaned = utils.clean_answers(answers, ["Name", "Animal", "Thing"])
    assert cleaned == {"Name": "Bisi", "Thing": "y" * utils.MAX_ANSWER_LEN}
    assert utils.clean_answers("nope", ["Name"]) == {}


# --- FlaskCon pack -------------------------------------------------------


def test_pack_matching_ignores_case_spaces_and_punctuation():
    for word in ["Blueprint", "url_for", "URL For", "url-for", "Moi Moi", "moimoi", "JOLLOF"]:
        category = "Lagos & Africa" if word.lower().replace(" ", "") in ("moimoi", "jollof") else "Python & Flask"
        assert packs.pack_word_status("flaskcon", category, word) == "valid", word


def test_unknown_pack_words_go_to_a_vote():
    assert packs.pack_word_status("flaskcon", "Python & Flask", "Bython") == "needs_vote"


def test_pack_leaves_other_categories_alone():
    assert packs.pack_word_status("flaskcon", "Name", "Bisi") is None
    assert packs.pack_word_status(None, "Python & Flask", "flask") is None
    assert packs.pack_word_status("nope", "Python & Flask", "flask") is None


def test_every_pack_letter_has_answers_in_every_themed_category():
    for pack_id, pack in packs.PACKS.items():
        for letter in pack["letters"].lower():
            for category, words in pack["words"].items():
                hits = [w for w in words if w.startswith(letter)]
                assert len(hits) >= 2, (pack_id, category, letter)
        assert 3 <= pack["default_rounds"] <= len(pack["letters"])
        assert set(pack["words"]) <= set(pack["categories"])


def test_answer_validity_uses_the_pack():
    answers = {
        "Animal": "Lion",
        "Python & Flask": "Lambda",
        "Lagos & Africa": "Lekki",
        "Thing": "Lamp",
    }
    report = utils.get_answer_validity(answers, "L", pack="flaskcon")
    assert report["Python & Flask"]["status"] == "valid"
    assert report["Lagos & Africa"]["status"] == "valid"
    assert report["Animal"]["status"] == "valid"


def test_answer_validity_still_checks_the_letter_first():
    report = utils.get_answer_validity({"Python & Flask": "Flask"}, "L", pack="flaskcon")
    assert report["Python & Flask"]["status"] == "invalid"


def test_without_a_pack_custom_categories_go_to_a_vote():
    report = utils.get_answer_validity({"Python & Flask": "Lambda"}, "L")
    assert report["Python & Flask"]["status"] == "needs_vote"
