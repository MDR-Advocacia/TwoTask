from app.models.legal_one import LegalOneUser
from app.services.batch_strategies.onerequest_strategy import OnerequestStrategy


def test_onerequest_notification_recipients_only_marked_active_users(db_session):
    db_session.add_all(
        [
            LegalOneUser(
                external_id=1,
                name="Recebe",
                email="recebe@example.test",
                is_active=True,
                notify_onerequest_errors=True,
            ),
            LegalOneUser(
                external_id=2,
                name="Nao recebe",
                email="nao-recebe@example.test",
                is_active=True,
                notify_onerequest_errors=False,
            ),
            LegalOneUser(
                external_id=3,
                name="Inativo",
                email="inativo@example.test",
                is_active=False,
                notify_onerequest_errors=True,
            ),
        ]
    )
    db_session.commit()

    strategy = OnerequestStrategy(db_session, client=None)

    assert strategy._get_failure_notification_recipients() == ["recebe@example.test"]
