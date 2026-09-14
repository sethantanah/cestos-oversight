import uuid
import pytest

from app.models.hr import Notification
from app.services.notification_service import NotificationService

pytestmark = pytest.mark.integration


async def test_notification_resolution_and_forwarding(identities, session_factory):
    user = identities["admin"]
    async with session_factory() as session:
        service = NotificationService(session, user)

        # 1. Create a notification
        notif = Notification(
            id=uuid.uuid4(),
            organization_id=user.organization_id,
            recipient_id=user.id,
            message="Critical equipment maintenance required for Excavator EX-01",
            domain="EQUIPMENT",
            priority_tag="CRITICAL",
            delivery_method="BOTH",
        )
        session.add(notif)
        await session.commit()

        # 2. Test mark read
        read_res = await service.mark_read(notif.id)
        assert read_res["read_at"] is not None

        # 3. Test resolve notification
        res = await service.resolve_notification(notif.id)
        assert res["is_resolved"] is True
        assert res["resolved_by_id"] == user.id

        # 4. Test forward notification to self/colleague
        fwd_res = await service.forward_notification(
            notif.id, target_user_id=user.id, notes="Please handle this maintenance urgently."
        )
        assert fwd_res["recipient_id"] == user.id
        assert "Forwarded by" in fwd_res["message"]


async def test_notification_schedule_creation_and_evaluation(identities, session_factory):
    user = identities["admin"]
    async with session_factory() as session:
        service = NotificationService(session, user)

        # 1. Create a granular inventory consumable schedule
        schedule_data = {
            "title": "Consumables Expiry 14-Day Lead Alert",
            "domain": "INVENTORY",
            "rule_type": "INVENTORY_CONSUMABLES_EXPIRY",
            "lead_time_days": 14,
            "frequency": "DAILY",
            "priority_tag": "CRITICAL",
            "delivery_method": "BOTH",
            "recipient_user_ids": [str(user.id)],
            "is_active": True,
        }
        sched = await service.create_schedule(schedule_data)
        assert sched.id is not None
        assert sched.domain == "INVENTORY"
        assert sched.priority_tag == "CRITICAL"

        # 2. Evaluate schedule
        generated = await service.evaluate_schedule(sched)
        assert isinstance(generated, int)

        # 3. List notifications
        items, total = await service.list_notifications(domain="INVENTORY")
        assert isinstance(items, list)

