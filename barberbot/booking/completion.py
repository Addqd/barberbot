"""Автоматическое завершение записей после окончания услуги.

Отдельной системы фоновых задач нет: используется уже установленный
APScheduler 3.x (``AsyncIOScheduler``) с единственной задачей, которая
периодически вызывает ``BookingService.complete_finished_bookings()``.
Обновление выполняется сразу при запуске (в том числе после перезапуска) и
далее по интервалу, без действий пользователей.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore[import-untyped]
from apscheduler.triggers.interval import IntervalTrigger  # type: ignore[import-untyped]

from barberbot.booking.errors import BookingError
from barberbot.booking.service import BookingService

logger = logging.getLogger(__name__)

#: Интервал проверки. Минута даёт статус «Завершена» практически сразу после
#: окончания услуги и не создаёт заметной нагрузки на базу.
COMPLETION_INTERVAL = timedelta(minutes=1)

#: Идентификатор единственной задачи планировщика.
COMPLETION_JOB_ID = "complete-finished-bookings"


class CompletionScheduler:
    """Периодическая проверка записей, чьё время окончания прошло."""

    def __init__(
        self,
        service: BookingService,
        *,
        interval: timedelta = COMPLETION_INTERVAL,
    ) -> None:
        self._service = service
        self._interval = interval
        self._scheduler = AsyncIOScheduler()

    @property
    def running(self) -> bool:
        """Запущен ли планировщик."""
        return bool(self._scheduler.running)

    async def start(self) -> None:
        """Сразу обновить статусы и включить периодическую проверку."""
        await self.complete_once()
        self._scheduler.add_job(
            self.complete_once,
            trigger=IntervalTrigger(seconds=self._interval.total_seconds()),
            id=COMPLETION_JOB_ID,
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            misfire_grace_time=None,
        )
        self._scheduler.start()

    async def complete_once(self) -> None:
        """Один проход обновления; ошибка БД не останавливает планировщик."""
        try:
            completed = await self._service.complete_finished_bookings()
        except BookingError as error:
            # Доменный текст безопасен: без SQL, DSN и параметров запроса.
            logger.warning("Не удалось обновить статусы записей: %s", error)
            return
        if completed:
            logger.info("Записи переведены в статус completed: %d", completed)

    def shutdown(self) -> None:
        """Остановить планировщик; повторный вызов безопасен."""
        if not self._scheduler.running:
            return
        self._scheduler.shutdown(wait=False)


__all__ = ["COMPLETION_INTERVAL", "COMPLETION_JOB_ID", "CompletionScheduler"]
