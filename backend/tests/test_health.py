"""TruthLens AI - Backend Health Endpoint Tests.

Validates the /api/health endpoint using FastAPI TestClient:
- HTTP 200 OK status code.
- JSON response structure matches HealthResponse schema.
- Expected application status, name, and version values.
No external network requests are made.
"""

import sys
from pathlib import Path
import unittest

# Ensure both repository root and backend directory are in sys.path
backend_dir = Path(__file__).resolve().parent.parent
root_dir = backend_dir.parent

if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from backend.tests.asgi_test_client import InProcessTestClient

try:
    from backend.app import app
    from backend.config import get_settings
except ModuleNotFoundError:
    from app import app  # type: ignore
    from config import get_settings  # type: ignore


class TestHealthEndpoint(unittest.TestCase):
    """Test suite for GET /api/health endpoint."""

    def setUp(self) -> None:
        """Initialize test client and load configuration settings."""
        self.client = InProcessTestClient(app)
        self.settings = get_settings()

    def test_health_returns_http_200(self) -> None:
        """Verify that GET /api/health responds with HTTP 200 OK."""
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)

    def test_health_response_structure(self) -> None:
        """Verify that the response contains all required schema fields and correct types."""
        response = self.client.get("/api/health")
        data = response.json()

        self.assertIsInstance(data, dict)
        self.assertIn("status", data)
        self.assertIn("app_name", data)
        self.assertIn("version", data)
        self.assertIn("environment", data)

        self.assertIsInstance(data["status"], str)
        self.assertIsInstance(data["app_name"], str)
        self.assertIsInstance(data["version"], str)
        self.assertIsInstance(data["environment"], str)

    def test_health_expected_application_status(self) -> None:
        """Verify that the reported status is 'ok' and matches application configuration."""
        response = self.client.get("/api/health")
        data = response.json()

        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["app_name"], self.settings.PROJECT_NAME)
        self.assertEqual(data["version"], self.settings.VERSION)
        self.assertEqual(data["environment"], self.settings.ENVIRONMENT)


# Standalone function tests for pytest discovery
def test_pytest_health_returns_http_200() -> None:
    """Pytest-style test: GET /api/health returns HTTP 200."""
    client = InProcessTestClient(app)
    response = client.get("/api/health")
    assert response.status_code == 200


def test_pytest_health_response_structure() -> None:
    """Pytest-style test: Validate JSON response structure."""
    client = InProcessTestClient(app)
    response = client.get("/api/health")
    data = response.json()
    assert isinstance(data, dict)
    assert "status" in data
    assert "app_name" in data
    assert "version" in data
    assert "environment" in data


def test_pytest_health_expected_application_status() -> None:
    """Pytest-style test: Validate application status and config values."""
    client = InProcessTestClient(app)
    settings = get_settings()
    response = client.get("/api/health")
    data = response.json()
    assert data["status"] == "ok"
    assert data["app_name"] == settings.PROJECT_NAME
    assert data["version"] == settings.VERSION
    assert data["environment"] == settings.ENVIRONMENT


if __name__ == "__main__":
    unittest.main()
