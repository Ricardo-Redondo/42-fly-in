from enum import Enum
from pydantic import BaseModel, Field, field_validator


COLORS: dict[str, tuple[int, int, int]] = {
    "red":      (255, 0, 0),
    "darkred":  (139, 0, 0),
    "crimson":  (220, 20, 60),
    "maroon":   (176, 48, 96),
    "orange":   (255, 165, 0),
    "gold":     (255, 215, 0),
    "yellow":   (255, 255, 0),
    "green":    (0, 255, 0),
    "lime":     (0, 255, 0),
    "teal":     (0, 128, 128),
    "cyan":     (0, 255, 255),
    "skyblue":  (135, 206, 235),
    "blue":     (0, 0, 255),
    "navy":     (0, 0, 128),
    "purple":   (160, 32, 240),
    "violet":   (238, 130, 238),
    "magenta":  (255, 0, 255),
    "pink":     (255, 192, 203),
    "brown":    (165, 42, 42),
    "salmon":   (250, 128, 114),
    "white":    (255, 255, 255),
    "gray":     (190, 190, 190),
    "black":    (0, 0, 0),
}

DEFAULT_COLOR: tuple[int, int, int] = (190, 190, 190)


class ZoneType(str, Enum):
    NORMAL = "normal"
    RESTRICTED = "restricted"
    PRIORITY = "priority"
    BLOCKED = "blocked"

    def __str__(self) -> str:
        return self.value


class Zone(BaseModel):
    name: str
    x: int
    y: int
    zone_type: ZoneType = ZoneType.NORMAL
    color: str | None = None
    max_drones: int = Field(1, gt=0)

    @field_validator("name")
    @classmethod
    def no_dashes_or_spaces(cls, v: str) -> str:
        if "-" in v:
            raise ValueError("zone name may not contain '-'")
        if " " in v:
            raise ValueError("zone name may not contain spaces")
        return v

    @property
    def is_passable(self) -> bool:
        return self.zone_type is not ZoneType.BLOCKED

    @property
    def entry_cost(self) -> int:
        if not self.is_passable:
            raise ValueError(
                f"zone {self.name!r} is blocked and cannot be entered"
            )
        return 2 if self.zone_type is ZoneType.RESTRICTED else 1


class Connection(BaseModel):
    a: str
    b: str
    max_link_capacity: int = Field(1, gt=0)

    @property
    def name(self) -> str:
        return f"{self.a}-{self.b}"


class FlyMap(BaseModel):
    nb_drones: int = Field(gt=0)
    zones: dict[str, Zone]
    connections: list[Connection]
    start: str
    end: str
