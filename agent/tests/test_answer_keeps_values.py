"""Answering the trade-off question must not quietly change the time or budget the parent gave."""

from gs_agent.agent import keep_stated_values

CARE_6 = [{"need": "grade_level", "mode": "require", "value": ["m"]},
          {"need": "after_school_care", "mode": "require", "value": "18:00"}]


def model_says(value, mode="prefer"):
    return [{"need": "grade_level", "mode": "require", "value": ["m"]},
            {"need": "after_school_care", "mode": mode, "value": value}]


def test_picking_the_program_keeps_care_until_6_but_allows_the_mode_change():
    new = model_says("17:00")
    assert keep_stated_values(CARE_6, new, "The library club works") == {"after_school_care"}
    assert new[1] == {"need": "after_school_care", "mode": "prefer", "value": "18:00"}


def test_an_answer_with_a_new_time_may_change_it():
    for answer in ("Pickup at 5 works", "Someone can get him at five", "A las cinco está bien"):
        new = model_says("17:00")
        assert keep_stated_values(CARE_6, new, answer) == set()
        assert new[1]["value"] == "17:00"


def test_a_new_query_may_change_anything():
    new = model_says("17:00", mode="require")
    assert keep_stated_values(CARE_6, new, None) == set() and new[1]["value"] == "17:00"


def test_budget_is_kept_when_the_parent_only_says_yes():
    before = [{"need": "cost", "mode": "require", "value": 10000}]
    new = [{"need": "cost", "mode": "prefer", "value": 16500}]
    assert keep_stated_values(before, new, "Yes, include them") == {"cost"} and new[0]["value"] == 10000


def test_values_the_parent_never_gave_can_be_filled_from_the_answer():
    before = [{"need": "after_school_care", "mode": "require", "value": None}]
    new = [{"need": "after_school_care", "mode": "require", "value": "18:00"}]
    assert keep_stated_values(before, new, "Until 6") == set() and new[0]["value"] == "18:00"
    new = [{"need": "after_school_care", "mode": "require", "value": "18:00"}]
    assert keep_stated_values(before, new, "Yes") == set() and new[0]["value"] == "18:00"
