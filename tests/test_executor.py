from computer_agent_mcp.config import ServerConfig
from computer_agent_mcp.executor import ActionExecutor
from computer_agent_mcp.models import DisplayInfo


class PassiveMonitor:
    def arm(self) -> None:
        pass

    def disarm(self) -> None:
        pass

    def interrupted(self) -> bool:
        return False

    def consume_signal(self):
        return None


class DummyAdapter:
    def require_display(self, display_id: str):
        return type(
            "Descriptor",
            (),
            {"width_px": 1000, "height_px": 500, "scale_factor": 1.0},
        )()


def test_map_point_scales_from_worker_image_to_target_display():
    executor = ActionExecutor(
        adapter=DummyAdapter(),
        monitor=PassiveMonitor(),
        config=ServerConfig(),
    )
    state = type(
        "State",
        (),
        {
            "display_id": "primary",
            "display": DisplayInfo(
                id="primary",
                name="d",
                is_primary=True,
                width_px=2000,
                height_px=1000,
                logical_width=1000,
                logical_height=500,
                scale_factor=2.0,
                origin_x_px=0,
                origin_y_px=0,
                logical_origin_x=0,
                logical_origin_y=0,
            ),
        },
    )()
    mapped = executor._map_point(state, 1000, 500, source_width=2000, source_height=1000)
    assert mapped == (500, 250)
