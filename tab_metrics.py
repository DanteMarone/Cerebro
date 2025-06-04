from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel
from metrics import average_response_time


class MetricsTab(QWidget):
    """Displays statistics about agent activity."""

    def __init__(self, parent_app):
        super().__init__()
        self.parent_app = parent_app

        self.layout = QVBoxLayout(self)
        self.setLayout(self.layout)

        self.tool_usage_label = QLabel()
        self.task_completion_label = QLabel()
        self.response_time_label = QLabel()

        self.layout.addWidget(self.tool_usage_label)
        self.layout.addWidget(self.task_completion_label)
        self.layout.addWidget(self.response_time_label)

        self.refresh_metrics()

    def refresh_metrics(self):
        metrics = self.parent_app.metrics

        tool_lines = ["Tool Usage:"]
        for name, count in metrics.get("tool_usage", {}).items():
            tool_lines.append(f"- {name}: {count}")
        if len(tool_lines) == 1:
            tool_lines.append("None recorded")
        self.tool_usage_label.setText("\n".join(tool_lines))

        task_lines = ["Task Completions:"]
        for agent, count in metrics.get("task_completion_counts", {}).items():
            task_lines.append(f"- {agent}: {count}")
        if len(task_lines) == 1:
            task_lines.append("None recorded")
        self.task_completion_label.setText("\n".join(task_lines))

        resp_lines = ["Average Response Times:"]
        for agent in metrics.get("response_times", {}).keys():
            avg = average_response_time(metrics, agent)
            resp_lines.append(f"- {agent}: {avg:.2f}s")
        if len(resp_lines) == 1:
            resp_lines.append("None recorded")
        self.response_time_label.setText("\n".join(resp_lines))
