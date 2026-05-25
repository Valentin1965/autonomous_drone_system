class CVNavigator:
    """
    Модуль навігації на основі комп'ютерного бачення.
    Отримує координати цілі від детектора і передає їх у OFFBOARD-контролер.
    """

    def __init__(self, offboard_controller, logger=None):
        self.offboard = offboard_controller
        self.logger = logger

    def follow_dummy_target(self):
        """
        Заглушка: тримає позицію, не рухається.
        Можна розширити до:
        - слідування за об'єктом
        - уникнення перешкод
        - автономної навігації
        """
        if self.logger:
            self.logger.info("CV navigation stub: no real target, holding position.")
