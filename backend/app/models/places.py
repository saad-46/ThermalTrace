from geoalchemy2 import Geography
from sqlalchemy import BigInteger, Float, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class Place(Base):
    """A populated place from GeoNames (cities500), used to name events offline ("near <place>")."""

    __tablename__ = "places"
    __table_args__ = (Index("ix_places_geom", "geom", postgresql_using="gist"),)

    geonameid: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    admin1: Mapped[str | None] = mapped_column(String(120))  # state / province
    country_code: Mapped[str] = mapped_column(String(2), nullable=False)
    population: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    geom = mapped_column(Geography("POINT", srid=4326, spatial_index=False), nullable=False)
