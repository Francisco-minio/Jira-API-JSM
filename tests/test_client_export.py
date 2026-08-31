import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import Client, CompanyInformer, ClientCompany
from app.services.reports import build_clients_export_data

SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture
def db_session():
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    c1 = Client(name="Juan Pérez", email="juan@empresa.cl", jira_account_id="jira-123", active=True)
    c2 = Client(name="María Gómez", email="maria@empresa.cl", jira_account_id="jira-456", active=True)
    db.add_all([c1, c2])
    db.commit()

    comp = ClientCompany(name="Empresa Test", active=True)
    db.add(comp)
    db.commit()

    inf = CompanyInformer(company_id=comp.id, name="Pedro Informador", email="pedro@empresa.cl", active=True)
    db.add(inf)
    db.commit()

    yield db

    db.close()
    Base.metadata.drop_all(bind=engine)


def test_build_clients_export_data(db_session):
    data = build_clients_export_data(db_session)
    assert len(data) == 3

    emails = [row["email"] for row in data]
    assert "juan@empresa.cl" in emails
    assert "maria@empresa.cl" in emails
    assert "pedro@empresa.cl" in emails

    names = [row["name"] for row in data]
    assert "Juan Pérez" in names
    assert "María Gómez" in names
    assert "Pedro Informador" in names
