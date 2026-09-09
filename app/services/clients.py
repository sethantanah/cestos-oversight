import math
import uuid
from datetime import UTC, datetime

from fastapi import Request
from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.models import Client, User
from app.repositories.base import organization_query
from app.schemas.client import ClientCreate, ClientRead, ClientUpdate
from app.schemas.common import Page
from app.services.audit import RequestMetadata, record_audit, request_metadata
from app.services.counters import next_business_number


class ClientService:
    def __init__(self, session: AsyncSession, actor: User):
        self.session = session
        self.actor = actor

    def _scope(self) -> Select[tuple[Client]]:
        return organization_query(Client, self.actor.organization_id)

    async def get(self, client_id: uuid.UUID) -> ClientRead:
        client = (
            await self.session.scalars(self._scope().where(Client.id == client_id))
        ).one_or_none()
        if client is None:
            raise NotFoundError("Client not found")
        return ClientRead.model_validate(client)

    async def list(
        self,
        page: int,
        page_size: int,
        search: str | None = None,
        is_active: bool | None = None,
    ) -> Page[ClientRead]:
        query = self._scope()
        if search:
            like = f"%{search}%"
            query = query.where(or_(Client.client_number.ilike(like), Client.name.ilike(like)))
        if is_active is not None:
            query = query.where(Client.is_active == is_active)
        total = await self.session.scalar(select(func.count()).select_from(query.subquery()))
        rows = (
            await self.session.scalars(
                query.order_by(Client.created_at, Client.id)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
        items = [ClientRead.model_validate(row) for row in rows]
        return Page(
            items=items,
            total=total or 0,
            page=page,
            page_size=page_size,
            pages=math.ceil((total or 0) / page_size) if page_size else 0,
        )

    async def create(self, body: ClientCreate, request: Request | None = None) -> ClientRead:
        try:
            number = await next_business_number(self.session, self.actor.organization_id, "client")
            client = Client(
                organization_id=self.actor.organization_id,
                client_number=number,
                name=body.name,
                legal_name=body.legal_name,
                primary_contact_name=body.primary_contact_name,
                primary_contact_email=body.primary_contact_email,
                primary_contact_phone=body.primary_contact_phone,
                address=body.address,
                country=body.country,
                billing_email=body.billing_email,
                notes=body.notes,
                created_by_id=self.actor.id,
                updated_by_id=self.actor.id,
            )
            self.session.add(client)
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
                action="client.created",
                entity_type="client",
                entity_id=client.id,
                new_values={"client_number": number, "name": body.name},
                **meta,
            )
            await self.session.commit()
            return ClientRead.model_validate(client)
        except ConflictError:
            await self.session.rollback()
            raise
        except Exception:
            await self.session.rollback()
            raise

    async def update(
        self, client_id: uuid.UUID, body: ClientUpdate, request: Request | None = None
    ) -> ClientRead:
        try:
            client = (
                await self.session.scalars(self._scope().where(Client.id == client_id))
            ).one_or_none()
            if client is None:
                raise NotFoundError("Client not found")
            for key, value in body.model_dump(exclude_unset=True).items():
                setattr(client, key, value)
            client.updated_by_id = self.actor.id
            client.updated_at = datetime.now(UTC)
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
                action="client.updated",
                entity_type="client",
                entity_id=client.id,
                new_values={"name": client.name},
                **meta,
            )
            await self.session.commit()
            return ClientRead.model_validate(client)
        except (NotFoundError, ConflictError):
            await self.session.rollback()
            raise
        except Exception:
            await self.session.rollback()
            raise
