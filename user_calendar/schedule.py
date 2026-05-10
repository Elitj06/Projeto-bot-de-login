"""
Calendário de Vagas por Usuário.

Cada usuário seleciona os dias da semana e faixas de horário
em que quer concorrer a vagas.

Estrutura:
  user_schedule = {
      "user_id": "...",
      "targets": [
          {"day": "seg", "time_slots": ["06:00-08:00", "08:00-10:00"]},
          {"day": "qua", "time_slots": ["06:00-08:00"]},
          {"day": "qui", "time_slots": ["06:00-21:00"]},  # dia inteiro
      ]
  }

Dias: seg, ter, qua, qui, sex, sab, dom
Horários: faixas de 2h ou customizadas
"""
from dataclasses import dataclass, field
from typing import Optional

from core.logger import LoggerFactory

logger = LoggerFactory.get_logger(__name__)

DAYS_OF_WEEK = ["seg", "ter", "qua", "qui", "sex", "sab", "dom"]
DAY_LABELS = {
    "seg": "Segunda", "ter": "Terça", "qua": "Quarta",
    "qui": "Quinta", "sex": "Sexta", "sab": "Sábado", "dom": "Domingo",
}

# Faixas de horário padrão do SEAP
DEFAULT_TIME_SLOTS = [
    "06:00-08:00",
    "08:00-10:00",
    "10:00-12:00",
    "12:00-14:00",
    "14:00-16:00",
    "16:00-18:00",
    "18:00-20:00",
    "20:00-22:00",
]


@dataclass
class DaySchedule:
    """Agenda de um dia da semana."""
    day: str
    enabled: bool = False
    time_slots: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"day": self.day, "enabled": self.enabled, "time_slots": self.time_slots}

    @classmethod
    def from_dict(cls, data: dict) -> "DaySchedule":
        return cls(
            day=data.get("day", ""),
            enabled=data.get("enabled", False),
            time_slots=data.get("time_slots", []),
        )


@dataclass
class UserSchedule:
    """Agenda completa de um usuário."""
    user_id: str
    username: str = ""
    days: list[DaySchedule] = field(default_factory=list)

    def __post_init__(self):
        if not self.days:
            self.days = [DaySchedule(day=d) for d in DAYS_OF_WEEK]

    def get_enabled_days(self) -> list[DaySchedule]:
        return [d for d in self.days if d.enabled]

    def has_target_for(self, day: str, time: str) -> bool:
        """Verifica se o usuário tem alvo para um dia/horário específico."""
        for d in self.days:
            if d.day == day and d.enabled:
                for slot in d.time_slots:
                    start, end = slot.split("-")
                    if start <= time < end:
                        return True
        return False

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "username": self.username,
            "days": [d.to_dict() for d in self.days],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "UserSchedule":
        days = [DaySchedule.from_dict(d) for d in data.get("days", [])]
        return cls(
            user_id=data.get("user_id", ""),
            username=data.get("username", ""),
            days=days,
        )


def default_schedule(user_id: str, username: str = "") -> UserSchedule:
    """Cria agenda vazia para um usuário."""
    return UserSchedule(user_id=user_id, username=username)


def schedule_from_targets(user_id: str, targets: list[dict]) -> UserSchedule:
    """
    Cria agenda a partir de targets simplificados.

    Args:
        targets: [{"day": "seg", "time_slots": ["06:00-08:00"]}, ...]
    """
    days = []
    target_map = {t["day"]: t.get("time_slots", []) for t in targets}

    for d in DAYS_OF_WEEK:
        if d in target_map:
            days.append(DaySchedule(day=d, enabled=True, time_slots=target_map[d]))
        else:
            days.append(DaySchedule(day=d, enabled=False))

    return UserSchedule(user_id=user_id, days=days)
