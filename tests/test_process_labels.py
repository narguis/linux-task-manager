import unittest
from dataclasses import replace

from test_grouping import process
from linux_task_manager.process_labels import process_display_name


class ProcessLabelTests(unittest.TestCase):
    def test_labels_browser_main_process(self) -> None:
        root = process(10, "chrome", app=True)
        self.assertEqual(
            process_display_name(root, root, "Google Chrome"),
            "Google Chrome · Main process",
        )

    def test_labels_renderer_with_client_id(self) -> None:
        root = process(10, "chrome", app=True)
        renderer = process(11, "chrome", ppid=10)
        renderer = replace(
            renderer,
            command=(
                "/opt/google/chrome/chrome --type=renderer "
                "--crashpad-handler-pid=123 --renderer-client-id=17"
            ),
        )
        self.assertEqual(
            process_display_name(renderer, root, "Google Chrome"),
            "Google Chrome · Renderer #17",
        )

    def test_labels_utility_subtype(self) -> None:
        root = process(10, "chrome", app=True)
        utility = process(11, "chrome", ppid=10)
        utility = replace(
            utility,
            command=(
                "/opt/google/chrome/chrome --type=utility "
                "--utility-sub-type=network.mojom.NetworkService"
            ),
        )
        self.assertEqual(
            process_display_name(utility, root, "Google Chrome"),
            "Google Chrome · Network service",
        )


if __name__ == "__main__":
    unittest.main()
