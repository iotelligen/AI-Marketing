import unittest
from unittest import mock

from tests import _env

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.database import get_db
from app.models.marketing_post import MarketingPost
from app.models.publish_account import PublishAccount
from app.routers import marketing as marketing_router
from app.services import marketing_publish_service


SLUG = _env.WORKSPACE_SLUG


class MarketingPublishApiTests(unittest.TestCase):
    def setUp(self):
        self.session_factory = _env.new_session_factory()

        app = FastAPI()
        app.include_router(marketing_router.router)

        def override_get_db():
            db = self.session_factory()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

    def create_draft_post(self, *, status="draft") -> str:
        with self.session_factory() as db:
            post = MarketingPost(
                workspace_slug=SLUG,
                topic="Predictive maintenance for motors",
                platform="linkedin",
                target_audience="Factory owners",
                objective="Generate leads",
                language="English",
                title="Stop unplanned downtime",
                content=(
                    "Motor failures still catch plants off guard. "
                    "Condition monitoring gives maintenance teams hours of warning."
                ),
                hashtags=["#IIoT", "#PredictiveMaintenance"],
                sources=[],
                llm_model="test-model",
                status=status,
                publish_metadata={},
            )
            db.add(post)
            db.commit()
            db.refresh(post)
            return post.id

    def test_dry_run_publish_auto_approves_draft(self):
        post_id = self.create_draft_post()

        response = self.client.post(
            f"/marketing/posts/{post_id}/publish",
            json={
                "dry_run": True,
                "auto_approve": True,
                "requested_by": "dashboard",
            },
        )

        self.assertEqual(response.status_code, 202, response.text)
        body = response.json()
        self.assertEqual(body["status"], "dry_run")
        self.assertTrue(body["remote_post_id"].startswith("dry-run-"))
        self.assertIsNone(body["publish_error"])
        self.assertTrue(body["publish_metadata"]["dry_run"])

    def test_publish_without_auto_approve_rejects_draft(self):
        post_id = self.create_draft_post()

        response = self.client.post(
            f"/marketing/posts/{post_id}/publish",
            json={
                "dry_run": True,
                "auto_approve": False,
            },
        )

        self.assertEqual(response.status_code, 422)
        self.assertIn("approved", response.json()["detail"].lower())

    def test_second_publish_is_idempotent(self):
        post_id = self.create_draft_post(status="approved")

        first = self.client.post(
            f"/marketing/posts/{post_id}/publish",
            json={"dry_run": True},
        ).json()
        second = self.client.post(
            f"/marketing/posts/{post_id}/publish",
            json={"dry_run": True},
        ).json()

        self.assertEqual(first["remote_post_id"], second["remote_post_id"])
        self.assertEqual(second["status"], "dry_run")

    def test_live_publish_fails_without_account(self):
        post_id = self.create_draft_post(status="approved")

        response = self.client.post(
            f"/marketing/posts/{post_id}/publish",
            json={"dry_run": False, "auto_approve": False},
        )

        self.assertEqual(response.status_code, 202, response.text)
        body = response.json()
        self.assertEqual(body["status"], "approved")
        self.assertIn(
            "No active LinkedIn publish account",
            body["publish_error"],
        )

    def test_live_publish_calls_linkedin_text_provider(self):
        post_id = self.create_draft_post(status="approved")

        with self.session_factory() as db:
            db.add(
                PublishAccount(
                    workspace_slug=SLUG,
                    platform="linkedin",
                    display_name="Company page",
                    status="active",
                    credentials={
                        "access_token": "token-value",
                        "author_urn": "urn:li:organization:123",
                    },
                )
            )
            db.commit()

        with mock.patch(
            "app.services.marketing_publish_service.LinkedInPublishProvider"
        ) as provider_cls:
            provider_cls.return_value.publish_text.return_value = {
                "provider": "linkedin",
                "remote_post_id": "urn:li:share:999",
                "remote_url": None,
                "content_type": "text",
            }

            response = self.client.post(
                f"/marketing/posts/{post_id}/publish",
                json={"dry_run": False},
            )

        self.assertEqual(response.status_code, 202, response.text)
        body = response.json()
        self.assertEqual(body["status"], "published")
        self.assertEqual(body["remote_post_id"], "urn:li:share:999")
        provider_cls.return_value.publish_text.assert_called_once()
        caption = provider_cls.return_value.publish_text.call_args.kwargs["text"]
        self.assertIn("Stop unplanned downtime", caption)
        self.assertIn("#IIoT", caption)

    def test_generate_and_publish_dry_run(self):
        with mock.patch.object(
            marketing_router,
            "retrieve_knowledge",
            return_value=([], []),
        ), mock.patch.object(
            marketing_router,
            "generate_marketing_post",
            return_value={
                "title": "Generated title",
                "content": "Generated body about condition monitoring.",
                "hashtags": ["#IoTelliGen"],
                "llm_model": "test-model",
                "skills_used": ["brand-guidelines"],
            },
        ):
            response = self.client.post(
                "/marketing/posts/generate-and-publish",
                json={
                    "topic": "Condition monitoring for industrial motors",
                    "workspace": SLUG,
                    "platform": "linkedin",
                    "dry_run": True,
                    "requested_by": "dashboard",
                },
            )

        self.assertEqual(response.status_code, 201, response.text)
        body = response.json()
        self.assertEqual(body["title"], "Generated title")
        self.assertEqual(body["status"], "dry_run")
        self.assertEqual(body["workspace_slug"], SLUG)
        self.assertTrue(body["remote_post_id"].startswith("dry-run-"))

    def test_build_post_caption_includes_hashtags(self):
        post = MarketingPost(
            workspace_slug=SLUG,
            topic="t",
            platform="linkedin",
            title="Title",
            content="Body text",
            hashtags=["#One", "#Two"],
            sources=[],
            llm_model="m",
            status="draft",
            publish_metadata={},
        )

        caption = marketing_publish_service.build_post_caption(post)
        self.assertEqual(caption, "Title\n\nBody text\n\n#One #Two")


if __name__ == "__main__":
    unittest.main()
