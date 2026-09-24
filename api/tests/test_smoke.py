from campusclaw.main import app


def test_application_imports() -> None:
    assert app.title == "CampusClaw API"
