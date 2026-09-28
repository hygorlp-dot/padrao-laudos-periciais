"""Physical visit facts explicitly confirmed by the expert, not session clocks."""

from dataclasses import asdict, dataclass, fields
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import re


@dataclass(frozen=True, slots=True)
class VisitAttendant:
    name: str
    role: str
    presence_confirmed: bool

    def __post_init__(self):
        if any(type(value) is not str or not value.strip() or len(value) > 300 for value in (self.name, self.role)) or self.presence_confirmed is not True:
            raise ValueError("visit attendance requires explicit confirmation")


@dataclass(frozen=True, slots=True)
class VisitContext:
    date: str
    start_time: str
    end_time: str | None
    weather: str | None
    temperature_c: str | None
    relative_humidity_percent: str | None
    attendants: tuple[VisitAttendant, ...]
    confirmed_by: str
    confirmed_at: str

    def __post_init__(self):
        if type(self.date) is not str or re.fullmatch(r"\d{4}-\d{2}-\d{2}", self.date) is None:
            raise ValueError("physical visit date is invalid")
        date.fromisoformat(self.date)
        for value, nullable in ((self.start_time, False), (self.end_time, True)):
            if value is None and nullable:
                continue
            if type(value) is not str or re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value) is None:
                raise ValueError("physical visit time is invalid")
        if self.end_time is not None and self.end_time < self.start_time:
            raise ValueError("visit end precedes start on the recorded date")
        if self.weather is not None and (type(self.weather) is not str or not self.weather.strip() or len(self.weather) > 300):
            raise ValueError("visit weather is invalid")
        for value, minimum, maximum in ((self.temperature_c, Decimal("-273.15"), None), (self.relative_humidity_percent, Decimal(0), Decimal(100))):
            if value is not None:
                try:
                    if type(value) is not str or not value.strip():
                        raise ValueError("visit measurement must retain an explicit value")
                    number = Decimal(value.replace(",", "."))
                    if not number.is_finite() or number < minimum or (maximum is not None and number > maximum):
                        raise ValueError("visit measurement is invalid")
                except InvalidOperation as exc:
                    raise ValueError("visit measurement is invalid") from exc
        if type(self.attendants) is not tuple or any(type(item) is not VisitAttendant for item in self.attendants) or len({(item.name, item.role) for item in self.attendants}) != len(self.attendants):
            raise ValueError("visit attendants are invalid")
        if type(self.confirmed_by) is not str or not self.confirmed_by.strip() or type(self.confirmed_at) is not str:
            raise ValueError("visit professional confirmation is invalid")
        if datetime.fromisoformat(self.confirmed_at).utcoffset() is None:
            raise ValueError("visit confirmation requires timezone")

    @classmethod
    def from_values(cls, values, *, confirmed_by, confirmed_at):
        if type(values) is not dict or set(values) != {f.name for f in fields(cls)} - {"confirmed_by", "confirmed_at"} or type(values["attendants"]) is not list:
            raise ValueError("visit values are invalid")
        try:
            attendants = tuple(VisitAttendant(**row) for row in values["attendants"])
        except TypeError as exc:
            raise ValueError("visit attendant values are invalid") from exc
        return cls(**{**values, "attendants": attendants}, confirmed_by=confirmed_by, confirmed_at=confirmed_at)

    @classmethod
    def from_mapping(cls, value):
        if type(value) is not dict or set(value) != {f.name for f in fields(cls)}:
            raise ValueError("visit context is invalid")
        return cls.from_values({k: v for k, v in value.items() if k not in {"confirmed_by", "confirmed_at"}}, confirmed_by=value["confirmed_by"], confirmed_at=value["confirmed_at"])

    def as_dict(self):
        return {**asdict(self), "attendants": [asdict(item) for item in self.attendants]}
