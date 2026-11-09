import json
import unittest

from types import SimpleNamespace
from unittest import mock

from tests import _env

from pydantic import ValidationError

from app.models.brand_profile import BrandProfile
from app.schemas.video_planner import (
    VideoFormat,
    VideoPlan,
    VideoPlanRequest,
)
from app.services import llm_json
from app.services import video_planner_service
from app.services.video_planner_service import generate_video_plan


SLUG = _env.WORKSPACE_SLUG

FORMAT = {
    "format_name": "Problem to solution",
    "rationale": "Short awareness video",
    "duration_seconds": 15,
    "beats": [
        {"beat": "hook", "duration_seconds": 3, "goal": "Stop the scroll"},
        {
            "beat": "pain_point",
            "duration_seconds": 4,
            "goal": "Name the downtime problem",
        },
        {
            "beat": "solution",
            "duration_seconds": 4,
            "goal": "Show monitoring as the answer",
        },
        {"beat": "cta", "duration_seconds": 4, "goal": "Invite contact"},
    ],
}


def script(scene_count: int = 4) -> dict:
    """
    A scriptwriter answer that gets the timing and numbering wrong on
    purpose. The planner must overwrite both from the beat sheet.
    """
    return {
        "concept": "Concept",
        "title": "Motor monitoring",
        "duration_seconds": 999,
        "aspect_ratio": "16:9",
        "cta": "Talk to us",
        "scenes": [
            {
                "scene_number": 7,
                "duration_seconds": 60,
                "beat": "benefit",
                "narration": f"Narration {index}",
                "visual_prompt": f"Visual {index}",
                "on_screen_text": f"Text {index}",
                "transition": "fade",
            }
            for index in range(1, scene_count + 1)
        ],
    }


def llm_reply(payload) -> SimpleNamespace:
    content = payload if isinstance(payload, str) else json.dumps(payload)

    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


def beat(name: str, seconds: int) -> dict:
    return {"beat": name, "duration_seconds": seconds, "goal": "A goal"}


class VideoFormatSchemaTests(unittest.TestCase):
    def test_valid_format_is_accepted(self):
        video_format = VideoFormat.model_validate(FORMAT)

        self.assertEqual(len(video_format.beats), 4)

    def test_beat_durations_must_total_the_video_duration(self):
        data = {**FORMAT, "duration_seconds": 20}

        with self.assertRaisesRegex(ValidationError, "total 15s"):
            VideoFormat.model_validate(data)

    def test_first_beat_must_be_hook(self):
        data = {
            **FORMAT,
            "beats": [
                beat("pain_point", 5),
                beat("solution", 5),
                beat("cta", 5),
            ],
        }

        with self.assertRaisesRegex(ValidationError, "first beat"):
            VideoFormat.model_validate(data)

    def test_last_beat_must_be_cta(self):
        data = {
            **FORMAT,
            "beats": [
                beat("hook", 5),
                beat("cta", 5),
                beat("solution", 5),
            ],
        }

        with self.assertRaisesRegex(ValidationError, "last beat"):
            VideoFormat.model_validate(data)

    def test_only_one_cta_is_allowed(self):
        data = {
            **FORMAT,
            "beats": [
                beat("hook", 5),
                beat("cta", 5),
                beat("cta", 5),
            ],
        }

        with self.assertRaisesRegex(ValidationError, "one 'cta'"):
            VideoFormat.model_validate(data)

    def test_beat_cannot_outlast_one_ai_clip(self):
        data = {
            "format_name": "Too slow",
            "duration_seconds": 30,
            "beats": [
                beat("hook", 4),
                beat("solution", 20),
                beat("cta", 6),
            ],
        }

        with self.assertRaises(ValidationError):
            VideoFormat.model_validate(data)

    def test_unknown_beat_is_rejected(self):
        data = {
            **FORMAT,
            "beats": [
                beat("hook", 5),
                beat("testimonial", 5),
                beat("cta", 5),
            ],
        }

        with self.assertRaises(ValidationError):
            VideoFormat.model_validate(data)


class VideoPlanSchemaTests(unittest.TestCase):
    def legacy_plan(self) -> dict:
        return {
            "concept": "Concept",
            "title": "Title",
            "duration_seconds": 10,
            "aspect_ratio": "9:16",
            "language": "English",
            "target_audience": "Factory owners",
            "objective": "Awareness",
            "cta": "Contact us",
            "scenes": [
                {
                    "scene_number": number,
                    "duration_seconds": 5,
                    "purpose": "Purpose",
                    "narration": "Narration",
                    "visual_prompt": "Visual",
                    "on_screen_text": "Text",
                    "transition": "fade",
                }
                for number in (1, 2)
            ],
        }

    def test_storyboard_without_beats_still_validates(self):
        plan = VideoPlan.model_validate(self.legacy_plan())

        self.assertIsNone(plan.scenes[0].beat)

    def test_beats_cannot_be_set_on_only_some_scenes(self):
        data = self.legacy_plan()
        data["scenes"][0]["beat"] = "hook"

        with self.assertRaisesRegex(ValidationError, "Every scene"):
            VideoPlan.model_validate(data)

    def test_beat_order_is_enforced_on_storyboards(self):
        data = self.legacy_plan()
        data["scenes"][0]["beat"] = "cta"
        data["scenes"][1]["beat"] = "hook"

        with self.assertRaisesRegex(ValidationError, "first beat"):
            VideoPlan.model_validate(data)


class TwoAgentPlanningTests(unittest.TestCase):
    def setUp(self):
        self.session_factory = _env.new_session_factory()
        self.db = self.session_factory()
        self.addCleanup(self.db.close)

        self.db.add(BrandProfile(
            workspace_slug=SLUG,
            brand_name="IoTelliGen",
            tagline="Smarter factories",
            accent_color="#16C79A",
            phone="+880 1700 000000",
            email="sales@iotelligen.example",
        ))
        self.db.commit()

        knowledge = mock.patch.object(
            video_planner_service,
            "retrieve_knowledge",
            return_value=(
                ["Source: gateway.pdf\nContent:\nThe gateway reads vibration."],
                [{"filename": "gateway.pdf"}],
            ),
        )
        knowledge.start()
        self.addCleanup(knowledge.stop)

        completion = mock.patch.object(llm_json, "completion")
        self.completion = completion.start()
        self.addCleanup(completion.stop)

    def request(self, **overrides) -> VideoPlanRequest:
        data = {
            "topic": "Industrial motor condition monitoring",
            "workspace_slug": SLUG,
            "platform": "linkedin",
            "duration_seconds": 15,
            "aspect_ratio": "9:16",
        }
        data.update(overrides)

        return VideoPlanRequest.model_validate(data)

    def prompt(self, call_index: int, role: str = "system") -> str:
        messages = self.completion.call_args_list[call_index].kwargs["messages"]

        return next(
            message["content"]
            for message in messages
            if message["role"] == role
        )

    def test_format_agent_runs_before_the_script_agent(self):
        self.completion.side_effect = [llm_reply(FORMAT), llm_reply(script())]

        result = generate_video_plan(self.request(), self.db)

        self.assertEqual(self.completion.call_count, 2)
        self.assertIn("You decide the structure", self.prompt(0))
        self.assertIn("BEAT SHEET", self.prompt(1))
        self.assertEqual(result["format_agent"]["agent_id"], "video_format")
        self.assertEqual(result["agent_id"], "video")
        self.assertEqual(result["format"]["format_name"], "Problem to solution")

    def test_structure_comes_from_the_format_not_the_scriptwriter(self):
        self.completion.side_effect = [llm_reply(FORMAT), llm_reply(script())]

        plan = generate_video_plan(self.request(), self.db)["plan"]

        scenes = plan["scenes"]

        self.assertEqual(
            [scene["beat"] for scene in scenes],
            ["hook", "pain_point", "solution", "cta"],
        )
        self.assertEqual(
            [scene["duration_seconds"] for scene in scenes],
            [3, 4, 4, 4],
        )
        self.assertEqual(
            [scene["scene_number"] for scene in scenes],
            [1, 2, 3, 4],
        )
        self.assertEqual(scenes[1]["purpose"], "Name the downtime problem")
        self.assertEqual(scenes[1]["narration"], "Narration 2")
        self.assertEqual(plan["duration_seconds"], 15)
        self.assertEqual(plan["aspect_ratio"], "9:16")

        # The result must be a storyboard the rest of the API accepts.
        VideoPlan.model_validate(plan)

    def test_script_prompt_has_beats_skills_knowledge_and_brand(self):
        self.completion.side_effect = [llm_reply(FORMAT), llm_reply(script())]

        generate_video_plan(self.request(), self.db)

        prompt = self.prompt(1)

        self.assertIn("2. pain_point (4s): Name the downtime problem", prompt)
        self.assertIn("IoTelliGen Brand Guidelines", prompt)
        self.assertIn("LinkedIn", prompt)
        self.assertIn("The gateway reads vibration.", prompt)
        self.assertIn("Tagline: Smarter factories", prompt)

    def test_contact_details_are_never_sent_to_either_agent(self):
        self.completion.side_effect = [llm_reply(FORMAT), llm_reply(script())]

        generate_video_plan(self.request(), self.db)

        for call_index in (0, 1):
            for role in ("system", "user"):
                prompt = self.prompt(call_index, role)

                self.assertNotIn("1700", prompt)
                self.assertNotIn("sales@", prompt)

    def test_format_agent_is_told_why_its_answer_was_rejected(self):
        wrong_total = json.loads(json.dumps(FORMAT))
        wrong_total["beats"][1]["duration_seconds"] = 9

        self.completion.side_effect = [
            llm_reply(wrong_total),
            llm_reply(FORMAT),
            llm_reply(script()),
        ]

        result = generate_video_plan(self.request(), self.db)

        self.assertEqual(self.completion.call_count, 3)

        retry_messages = self.completion.call_args_list[1].kwargs["messages"]

        self.assertEqual(retry_messages[-2]["role"], "assistant")
        self.assertIn("total 20s", retry_messages[-1]["content"])
        self.assertEqual(result["plan"]["duration_seconds"], 15)

    def test_format_agent_cannot_change_the_requested_duration(self):
        longer = json.loads(json.dumps(FORMAT))
        longer["duration_seconds"] = 60

        self.completion.side_effect = [llm_reply(longer), llm_reply(script())]

        result = generate_video_plan(self.request(), self.db)

        self.assertEqual(result["format"]["duration_seconds"], 15)

    def test_wrong_scene_count_fails_after_the_retry(self):
        self.completion.side_effect = [
            llm_reply(FORMAT),
            llm_reply(script(scene_count=3)),
            llm_reply(script(scene_count=5)),
        ]

        with self.assertRaisesRegex(ValueError, "exactly 4 scenes"):
            generate_video_plan(self.request(), self.db)

        self.assertEqual(self.completion.call_count, 3)

    def test_fenced_json_is_accepted(self):
        self.completion.side_effect = [
            llm_reply("```json\n" + json.dumps(FORMAT) + "\n```"),
            llm_reply("```json\n" + json.dumps(script()) + "\n```"),
        ]

        result = generate_video_plan(self.request(), self.db)

        self.assertEqual(len(result["plan"]["scenes"]), 4)

    def test_supplied_format_skips_the_format_agent(self):
        self.completion.side_effect = [llm_reply(script())]

        result = generate_video_plan(
            self.request(video_format=FORMAT),
            self.db,
        )

        self.assertEqual(self.completion.call_count, 1)
        self.assertIsNone(result["format_agent"])
        self.assertEqual(len(result["plan"]["scenes"]), 4)

    def test_supplied_format_must_match_the_requested_duration(self):
        with self.assertRaisesRegex(ValueError, "requested"):
            generate_video_plan(
                self.request(video_format=FORMAT, duration_seconds=30),
                self.db,
            )

        self.completion.assert_not_called()

    def test_each_agent_uses_its_own_model_setting(self):
        self.completion.side_effect = [llm_reply(FORMAT), llm_reply(script())]

        with mock.patch.dict(
            "os.environ",
            {
                "VIDEO_FORMAT_MODEL": "ollama/format-model",
                "VIDEO_MODEL": "ollama/script-model",
            },
        ):
            result = generate_video_plan(self.request(), self.db)

        models = [
            call.kwargs["model"]
            for call in self.completion.call_args_list
        ]

        self.assertEqual(models, ["ollama/format-model", "ollama/script-model"])
        self.assertEqual(
            result["format_agent"]["llm_model"],
            "ollama/format-model",
        )
        self.assertEqual(result["llm_model"], "ollama/script-model")

    def test_workspace_outside_the_agent_permissions_is_refused(self):
        with self.assertRaises(PermissionError):
            generate_video_plan(
                self.request(workspace_slug="someone-else"),
                self.db,
            )

        self.completion.assert_not_called()


if __name__ == "__main__":
    unittest.main()
