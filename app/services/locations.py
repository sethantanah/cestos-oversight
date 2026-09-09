import math
import uuid
from datetime import UTC, datetime

from fastapi import Request
from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.models import Location, Project, User
from app.models.location import LocationType
from app.repositories.base import organization_query
from app.schemas.common import Page
from app.schemas.location import LocationCreate, LocationRead, LocationUpdate
from app.services.audit import RequestMetadata, record_audit, request_metadata
from app.services.counters import next_business_number


class LocationService:
    def __init__(self, session: AsyncSession, actor: User):
        self.session = session
        self.actor = actor

    def _scope(self) -> Select[tuple[Location]]:
        return organization_query(Location, self.actor.organization_id)

    async def get(self, location_id: uuid.UUID) -> LocationRead:
        location = (
            await self.session.scalars(self._scope().where(Location.id == location_id))
        ).one_or_none()
        if location is None:
            raise NotFoundError("Location not found")
        return LocationRead.model_validate(location)

    async def list(
        self,
        page: int,
        page_size: int,
        search: str | None = None,
        location_type: LocationType | None = None,
        project_id: uuid.UUID | None = None,
        is_active: bool | None = None,
    ) -> Page[LocationRead]:
        query = self._scope()
        if search:
            like = f"%{search}%"
            query = query.where(
                or_(
                    Location.location_number.ilike(like),
                    Location.name.ilike(like),
                    Location.city.ilike(like),
                )
            )
        if location_type is not None:
            query = query.where(Location.location_type == location_type)
        if project_id is not None:
            query = query.where(Location.project_id == project_id)
        if is_active is not None:
            query = query.where(Location.is_active == is_active)
        total = await self.session.scalar(select(func.count()).select_from(query.subquery()))
        rows = (
            await self.session.scalars(
                query.order_by(Location.created_at, Location.id)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
        items = [LocationRead.model_validate(row) for row in rows]
        return Page(
            items=items,
            total=total or 0,
            page=page,
            page_size=page_size,
            pages=math.ceil((total or 0) / page_size) if page_size else 0,
        )

    async def create(self, body: LocationCreate, request: Request | None = None) -> LocationRead:
        try:
            if body.project_id is not None:
                project = (
                    await self.session.scalars(
                        select(Project).where(
                            Project.id == body.project_id,
                            Project.organization_id == self.actor.organization_id,
                        )
                    )
                ).one_or_none()
                if project is None:
                    raise NotFoundError("Project not found")
            number = await next_business_number(
                self.session, self.actor.organization_id, "location"
            )
            location = Location(
                organization_id=self.actor.organization_id,
                location_number=number,
                name=body.name,
                location_type=body.location_type,
                project_id=body.project_id,
                address=body.address,
                city=body.city,
                county_or_region=body.county_or_region,
                country=body.country,
                latitude=body.latitude,
                longitude=body.longitude,
                description=body.description,
            )
            self.session.add(location)
            await self.session.flush()
            meta: RequestMetadata = (
                request_metadata(request)
                if request is not None
                else {"ip_address": None, "user_agent": None}
            )
            record_audit(
                self.session,
                organization_id=self.actor.organization_id,
                actor_user_id=self.actor.id,
                action="location.created",
                entity_type="location",
                entity_id=location.id,
                new_values={"location_number": number, "name": body.name},
                **meta,
            )
            await self.session.commit()
            return LocationRead.model_validate(location)
        except (NotFoundError, ConflictError):
            await self.session.rollback()
            raise
        except Exception:
            await self.session.rollback()
            raise

    async def update(
        self, location_id: uuid.UUID, body: LocationUpdate, request: Request | None = None
    ) -> LocationRead:
        try:
            location = (
                await self.session.scalars(self._scope().where(Location.id == location_id))
            ).one_or_none()
            if location is None:
                raise NotFoundError("Location not found")
            data = body.model_dump(exclude_unset=True)
            if data.get("project_id") is not None:
                project = (
                    await self.session.scalars(
                        select(Project).where(
                            Project.id == data["project_id"],
                            Project.organization_id == self.actor.organization_id,
                        )
                    )
                ).one_or_none()
                if project is None:
                    raise NotFoundError("Project not found")
            for key, value in data.items():
                setattr(location, key, value)
            location.updated_at = datetime.now(UTC)
            await self.session.flush()
            meta: RequestMetadata = (
                request_metadata(request)
                if request is not None
                else {"ip_address": None, "user_agent": None}
            )
            record_audit(
                self.session,
                organization_id=self.actor.organization_id,
                actor_user_id=self.actor.id,
                action="location.updated",
                entity_type="location",
                entity_id=location.id,
                new_values={"name": location.name},
                **meta,
            )
            await self.session.commit()
            return LocationRead.model_validate(location)
        except (NotFoundError, ConflictError):
            await self.session.rollback()
            raise
        except Exception:
            await self.session.rollback()
            raise
