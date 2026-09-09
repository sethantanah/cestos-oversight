    # ---- location history ----

    async def list_location_history(self, asset_id: uuid.UUID) -> Sequence:
        """List location change history for an asset"""
        await self._get_or_404(asset_id)
        rows = (
            await self.session.scalars(
                organization_query(AssetLocationHistory, self.actor.organization_id)
                .where(AssetLocationHistory.asset_id == asset_id)
                .order_by(AssetLocationHistory.recorded_at.desc())
            )
        ).all()
        return rows

    async def record_location_event(
        self,
        asset_id: uuid.UUID,
        location_id: uuid.UUID,
        event_type: str,
        project_id: uuid.UUID | None = None,
        meter_reading: decimal.Decimal | None = None,
        notes: str | None = None,
        request: Request | None = None,
    ):
        """Record a location change event for an asset"""
        try:
            await self._get_or_404(asset_id)
            location = (
                await self.session.scalars(
                    select(Location).where(
                        Location.id == location_id,
                        Location.organization_id == self.actor.organization_id,
                    )
                )
            ).one_or_none()
            if location is None:
                raise NotFoundError("Location not found")
            
            event = AssetLocationHistory(
                organization_id=self.actor.organization_id,
                asset_id=asset_id,
                location_id=location_id,
                project_id=project_id,
                event_type=event_type,
                recorded_at=datetime.now(UTC),
                meter_reading=meter_reading,
                recorded_by_id=self.actor.id,
                notes=notes,
            )
            self.session.add(event)
            await self.session.flush()
            record_audit(
                self.session,
                organization_id=self.actor.organization_id,
                actor_user_id=self.actor.id,
                action="asset.location_changed",
                entity_type="asset_location_history",
                entity_id=event.id,
                new_values={"asset_id": str(asset_id), "event_type": event_type, "location_id": str(location_id)},
                **_meta(request),
            )
            await self.session.commit()
            return event
        except (NotFoundError, ConflictError, ValidationError):
            await self.session.rollback()
            raise
        except Exception:
            await self.session.rollback()
            raise

    # ---- status history ----

    async def change_status(
        self,
        asset_id: uuid.UUID,
        new_status: str,
        reason: str | None = None,
        request: Request | None = None,
    ):
        """Change asset operational status and record history"""
        try:
            asset = await self._get_or_404(asset_id)
            old_status = asset.status
            
            # Validate status transition
            if old_status == AssetStatus.DISPOSED and new_status != AssetStatus.DISPOSED:
                raise ConflictError("Cannot change status of a disposed asset")
            
            asset.status = new_status
            asset.updated_by_id = self.actor.id
            asset.updated_at = datetime.now(UTC)
            
            history = AssetStatusHistory(
                organization_id=self.actor.organization_id,
                asset_id=asset_id,
                previous_status=str(old_status),
                new_status=new_status,
                changed_at=datetime.now(UTC),
                changed_by_id=self.actor.id,
                reason=reason,
            )
            self.session.add(history)
            await self.session.flush()
            record_audit(
                self.session,
                organization_id=self.actor.organization_id,
                actor_user_id=self.actor.id,
                action="asset.status_changed",
                entity_type="asset_status_history",
                entity_id=history.id,
                new_values={"asset_id": str(asset_id), "old_status": str(old_status), "new_status": new_status},
                **_meta(request),
            )
            await self.session.commit()
            return AssetRead.model_validate(asset)
        except (NotFoundError, ConflictError, ValidationError):
            await self.session.rollback()
            raise
        except Exception:
            await self.session.rollback()
            raise

    # ---- insurance ----

    async def list_insurance(self, asset_id: uuid.UUID):
        """List insurance records for an asset"""
        await self._get_or_404(asset_id)
        rows = (
            await self.session.scalars(
                organization_query(AssetInsurance, self.actor.organization_id)
                .where(AssetInsurance.asset_id == asset_id)
                .order_by(AssetInsurance.expiry_date)
            )
        ).all()
        return rows

    async def add_insurance(
        self,
        asset_id: uuid.UUID,
        provider: str,
        policy_number: str,
        start_date: date,
        expiry_date: date,
        coverage_type: str | None = None,
        coverage_amount: decimal.Decimal | None = None,
        currency: str | None = None,
        premium_amount: decimal.Decimal | None = None,
        notes: str | None = None,
        request: Request | None = None,
    ):
        """Add insurance record for an asset"""
        try:
            await self._get_or_404(asset_id)
            if expiry_date < start_date:
                raise ValidationError("Expiry date cannot precede start date")
            
            insurance = AssetInsurance(
                organization_id=self.actor.organization_id,
                asset_id=asset_id,
                provider=provider,
                policy_number=policy_number,
                coverage_type=coverage_type,
                coverage_amount=coverage_amount,
                currency=currency,
                start_date=start_date,
                expiry_date=expiry_date,
                premium_amount=premium_amount,
                status="ACTIVE",
                notes=notes,
            )
            self.session.add(insurance)
            await self.session.flush()
            record_audit(
                self.session,
                organization_id=self.actor.organization_id,
                actor_user_id=self.actor.id,
                action="asset.insurance_added",
                entity_type="asset_insurance",
                entity_id=insurance.id,
                new_values={"asset_id": str(asset_id), "provider": provider, "policy_number": policy_number},
                **_meta(request),
            )
            await self.session.commit()
            return insurance
        except (NotFoundError, ConflictError, ValidationError):
            await self.session.rollback()
            raise
        except Exception:
            await self.session.rollback()
            raise

    async def get_expiring_insurance(self, days: int = 30) -> Sequence:
        """Get insurance records expiring within N days"""
        cutoff_date = (datetime.now(UTC) + __import__('datetime').timedelta(days=days)).date()
        rows = (
            await self.session.scalars(
                organization_query(AssetInsurance, self.actor.organization_id)
                .where(
                    AssetInsurance.expiry_date <= cutoff_date,
                    AssetInsurance.expiry_date >= datetime.now(UTC).date(),
                    AssetInsurance.status == "ACTIVE",
                )
                .order_by(AssetInsurance.expiry_date)
            )
        ).all()
        return rows

    # ---- registration ----

    async def list_registrations(self, asset_id: uuid.UUID):
        """List registration records for an asset"""
        await self._get_or_404(asset_id)
        rows = (
            await self.session.scalars(
                organization_query(AssetRegistration, self.actor.organization_id)
                .where(AssetRegistration.asset_id == asset_id)
                .order_by(AssetRegistration.expiry_date.desc())
            )
        ).all()
        return rows

    async def add_registration(
        self,
        asset_id: uuid.UUID,
        registration_type: str,
        registration_number: str,
        issuing_authority: str | None = None,
        issue_date: date | None = None,
        expiry_date: date | None = None,
        notes: str | None = None,
        request: Request | None = None,
    ):
        """Add registration record for an asset"""
        try:
            await self._get_or_404(asset_id)
            if expiry_date and issue_date and expiry_date < issue_date:
                raise ValidationError("Expiry date cannot precede issue date")
            
            registration = AssetRegistration(
                organization_id=self.actor.organization_id,
                asset_id=asset_id,
                registration_type=registration_type,
                registration_number=registration_number,
                issuing_authority=issuing_authority,
                issue_date=issue_date,
                expiry_date=expiry_date,
                status="ACTIVE",
                notes=notes,
            )
            self.session.add(registration)
            await self.session.flush()
            record_audit(
                self.session,
                organization_id=self.actor.organization_id,
                actor_user_id=self.actor.id,
                action="asset.registration_added",
                entity_type="asset_registration",
                entity_id=registration.id,
                new_values={"asset_id": str(asset_id), "type": registration_type, "number": registration_number},
                **_meta(request),
            )
            await self.session.commit()
            return registration
        except (NotFoundError, ConflictError, ValidationError):
            await self.session.rollback()
            raise
        except Exception:
            await self.session.rollback()
            raise

    async def get_expiring_registrations(self, days: int = 30) -> Sequence:
        """Get registrations expiring within N days"""
        cutoff_date = (datetime.now(UTC) + __import__('datetime').timedelta(days=days)).date()
        rows = (
            await self.session.scalars(
                organization_query(AssetRegistration, self.actor.organization_id)
                .where(
                    AssetRegistration.expiry_date <= cutoff_date,
                    AssetRegistration.expiry_date >= datetime.now(UTC).date(),
                    AssetRegistration.status == "ACTIVE",
                )
                .order_by(AssetRegistration.expiry_date)
            )
        ).all()
        return rows

    # ---- inspections ----

    async def list_inspections(
        self,
        asset_id: uuid.UUID,
        inspection_type: str | None = None,
        condition_status: str | None = None,
    ) -> Sequence:
        """List inspections for an asset with optional filters"""
        await self._get_or_404(asset_id)
        query = organization_query(AssetInspection, self.actor.organization_id).where(
            AssetInspection.asset_id == asset_id
        )
        if inspection_type:
            query = query.where(AssetInspection.inspection_type == inspection_type)
        if condition_status:
            query = query.where(AssetInspection.condition_status == condition_status)
        rows = (
            await self.session.scalars(
                query.order_by(AssetInspection.inspection_date.desc())
            )
        ).all()
        return rows

    async def create_inspection(
        self,
        asset_id: uuid.UUID,
        inspection_type: str,
        condition_status: str,
        project_id: uuid.UUID | None = None,
        location_id: uuid.UUID | None = None,
        meter_reading: decimal.Decimal | None = None,
        summary: str | None = None,
        defects_found: bool = False,
        defect_notes: str | None = None,
        follow_up_required: bool = False,
        request: Request | None = None,
    ):
        """Create an inspection record for an asset"""
        try:
            await self._get_or_404(asset_id)
            
            inspection = AssetInspection(
                organization_id=self.actor.organization_id,
                asset_id=asset_id,
                inspection_type=inspection_type,
                inspection_date=datetime.now(UTC),
                project_id=project_id,
                location_id=location_id,
                inspected_by_id=self.actor.id,
                meter_reading=meter_reading,
                condition_status=condition_status,
                summary=summary,
                defects_found=defects_found,
                defect_notes=defect_notes,
                follow_up_required=follow_up_required,
            )
            self.session.add(inspection)
            await self.session.flush()
            record_audit(
                self.session,
                organization_id=self.actor.organization_id,
                actor_user_id=self.actor.id,
                action="asset.inspection_created",
                entity_type="asset_inspection",
                entity_id=inspection.id,
                new_values={"asset_id": str(asset_id), "type": inspection_type, "status": condition_status},
                **_meta(request),
            )
            await self.session.commit()
            return inspection
        except (NotFoundError, ConflictError, ValidationError):
            await self.session.rollback()
            raise
        except Exception:
            await self.session.rollback()
            raise

    # ---- defects ----

    async def list_defects(
        self,
        asset_id: uuid.UUID,
        status: str | None = None,
        severity: str | None = None,
    ) -> Sequence:
        """List defects for an asset with optional filters"""
        await self._get_or_404(asset_id)
        query = organization_query(AssetDefect, self.actor.organization_id).where(
            AssetDefect.asset_id == asset_id
        )
        if status:
            query = query.where(AssetDefect.status == status)
        if severity:
            query = query.where(AssetDefect.severity == severity)
        rows = (
            await self.session.scalars(
                query.order_by(AssetDefect.reported_at.desc())
            )
        ).all()
        return rows

    async def report_defect(
        self,
        asset_id: uuid.UUID,
        severity: str,
        description: str,
        inspection_id: uuid.UUID | None = None,
        notes: str | None = None,
        request: Request | None = None,
    ):
        """Report a new defect for an asset"""
        try:
            await self._get_or_404(asset_id)
            
            defect = AssetDefect(
                organization_id=self.actor.organization_id,
                asset_id=asset_id,
                inspection_id=inspection_id,
                reported_at=datetime.now(UTC),
                reported_by_id=self.actor.id,
                severity=severity,
                description=description,
                status="OPEN",
                notes=notes,
            )
            self.session.add(defect)
            await self.session.flush()
            record_audit(
                self.session,
                organization_id=self.actor.organization_id,
                actor_user_id=self.actor.id,
                action="asset.defect_reported",
                entity_type="asset_defect",
                entity_id=defect.id,
                new_values={"asset_id": str(asset_id), "severity": severity},
                **_meta(request),
            )
            await self.session.commit()
            return defect
        except (NotFoundError, ConflictError, ValidationError):
            await self.session.rollback()
            raise
        except Exception:
            await self.session.rollback()
            raise

    async def resolve_defect(
        self,
        defect_id: uuid.UUID,
        asset_id: uuid.UUID,
        notes: str | None = None,
        request: Request | None = None,
    ):
        """Resolve/close a defect"""
        try:
            await self._get_or_404(asset_id)
            defect = (
                await self.session.scalars(
                    organization_query(AssetDefect, self.actor.organization_id).where(
                        AssetDefect.id == defect_id,
                        AssetDefect.asset_id == asset_id,
                    )
                )
            ).one_or_none()
            if defect is None:
                raise NotFoundError("Defect not found")
            
            defect.status = "RESOLVED"
            defect.resolved_at = datetime.now(UTC)
            if notes:
                defect.notes = notes
            
            await self.session.flush()
            record_audit(
                self.session,
                organization_id=self.actor.organization_id,
                actor_user_id=self.actor.id,
                action="asset.defect_resolved",
                entity_type="asset_defect",
                entity_id=defect.id,
                new_values={"asset_id": str(asset_id), "status": "RESOLVED"},
                **_meta(request),
            )
            await self.session.commit()
            return defect
        except (NotFoundError, ConflictError, ValidationError):
            await self.session.rollback()
            raise
        except Exception:
            await self.session.rollback()
            raise

    async def get_critical_defects(self) -> Sequence:
        """Get all open critical defects in the organization"""
        rows = (
            await self.session.scalars(
                organization_query(AssetDefect, self.actor.organization_id)
                .where(
                    AssetDefect.severity == "CRITICAL",
                    AssetDefect.status == "OPEN",
                )
                .order_by(AssetDefect.reported_at.desc())
            )
        ).all()
        return rows
