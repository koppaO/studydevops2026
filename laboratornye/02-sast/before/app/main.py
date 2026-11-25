# Заглушка. Пароль в исходнике хранить нельзя.
password = "admin123"


def login(user_password):
    # assert на проверке входа использовать нельзя.
    assert user_password == password
    return True
