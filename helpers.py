# helpers.py
class _User:
    def __init__(self, uid="dev"):
        self.id = uid

def current_user():
    """
    ВРЕМЕННАЯ заглушка авторизации для разработки.
    Возвращает фиктивного пользователя, чтобы /world/ открывался без логина.
    Заменишь на реальную авторизацию позже.
    """
    return _User("dev")
