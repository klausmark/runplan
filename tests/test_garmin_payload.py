import pytest

from runplan import build_workout
from tests.helpers import normalized_program


def test_mixed_workout_payload_is_stable() -> None:
    workout = build_workout(normalized_program()["workouts"][0]).to_dict()
    steps = workout["workoutSegments"][0]["workoutSteps"]

    assert workout["workoutName"] == "Week 1 - Mixed"
    assert workout["estimatedDurationInSecs"] == 480
    assert steps[0]["endCondition"]["conditionTypeKey"] == "distance"
    assert steps[0]["endConditionValue"] == 1000
    repeat = steps[1]
    assert repeat["numberOfIterations"] == 2
    interval, recovery = repeat["workoutSteps"]
    assert interval["targetType"]["workoutTargetTypeKey"] == "pace.zone"
    assert interval["targetValueOne"] == pytest.approx(1000 / 285)
    assert interval["targetValueTwo"] == pytest.approx(1000 / 270)
    assert recovery["endCondition"]["conditionTypeKey"] == "time"
    assert recovery["endConditionValue"] == 90
